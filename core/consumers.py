import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from .models import Bus, Message, PickupRequest, Driver
import logging

logger = logging.getLogger(__name__)

User = get_user_model()


class LocationConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for bus location updates."""

    async def connect(self):
        self.bus_id = self.scope["url_route"]["kwargs"].get("bus_id")
        self.group_name = f"bus_{self.bus_id}"
        self.sequence_number = 0
        self.is_driver = False  # ⭐ NEW: Track if this connection is from driver

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        user = self.scope.get("user")
        logger.info(
            f'LocationConsumer connected: bus_id={self.bus_id}, user={getattr(user, "id", None)}'
        )

        # ⭐ NEW: Check if this is the driver connecting (for tracking)
        if user and getattr(user, "is_authenticated", False):
            self.is_driver = await self._is_driver_for_bus(user.id, self.bus_id)
            logger.info(f"Connection is_driver={self.is_driver}")

        # ⭐ IMPROVED: For passengers, send last known location
        # For drivers, send tracking_status only
        if not self.is_driver:
            last_location = await self._get_last_bus_location(self.bus_id)

            if last_location:
                lat, lng = last_location
                logger.info(
                    f"📍 Sending last known location to passenger: lat={lat}, lng={lng}"
                )

                await self.send(
                    text_data=json.dumps(
                        {
                            "type": "location_update",
                            "lat": lat,
                            "lng": lng,
                            "is_historical": True,
                            "sequence": -1,
                        }
                    )
                )

                # Send waiting status (waiting for driver to start)
                await self.send(
                    text_data=json.dumps(
                        {
                            "type": "tracking_status",
                            "status": "waiting",
                            "message": "Waiting for driver to start tracking...",
                        }
                    )
                )
            else:
                logger.warning(f"⚠️ No location data found for bus {self.bus_id}")
                await self.send(
                    text_data=json.dumps(
                        {
                            "type": "tracking_status",
                            "status": "waiting",
                            "message": "Waiting for driver to start tracking...",
                        }
                    )
                )

    @database_sync_to_async
    def _is_driver_for_bus(self, user_id, bus_id):
        """Check if this user is the driver for this bus"""
        try:
            bus = Bus.objects.select_related("driver__user").filter(id=bus_id).first()
            if bus and bus.driver and bus.driver.user_id == user_id:
                return True
            return False
        except Exception as e:
            logger.exception(f"Error checking if user is driver: {e}")
            return False

    @database_sync_to_async
    def _get_last_bus_location(self, bus_id):
        """Get the last known location from database"""
        try:
            bus = Bus.objects.filter(id=bus_id).first()
            if not bus:
                logger.error(f"Bus not found: id={bus_id}")
                return None
            if bus.current_lat and bus.current_lng:
                logger.info(
                    f"✅ Found last location for bus {bus.number_plate}: {bus.current_lat}, {bus.current_lng}"
                )
                return (bus.current_lat, bus.current_lng)
            else:
                logger.warning(f"❌ No location data for bus {bus.number_plate}")
                return None
        except Exception as e:
            logger.exception(f"Error retrieving last bus location: {e}")
            return None

    async def disconnect(self, close_code):
        # ⭐ CRITICAL FIX: Only clear location if this is the DRIVER disconnecting
        # Passenger disconnections should NOT clear the bus location
        if self.is_driver:
            logger.info(f"🚗 DRIVER disconnecting - clearing bus location")
            await self._clear_bus_location(self.bus_id)

            # Notify all connected passengers that tracking stopped
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "tracking_status",
                    "status": "disconnected",
                    "message": "Driver stopped tracking",
                },
            )
        else:
            logger.info(f"👤 Passenger disconnecting - keeping bus location")

        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info(
            f"LocationConsumer disconnected: bus_id={self.bus_id}, code={close_code}"
        )

    async def receive(self, text_data=None, bytes_data=None):
        try:
            data = json.loads(text_data)
            logger.info(f"LocationConsumer received: {data}")
        except Exception as e:
            logger.error(f"LocationConsumer JSON parse error: {e}")
            return

        if data.get("type") == "location":
            # ⭐ NEW: Only accept location updates from drivers
            if not self.is_driver:
                logger.warning(f"Rejecting location update from non-driver")
                return

            lat = data.get("lat")
            lng = data.get("lng")

            if lat is None or lng is None:
                logger.warning(f"LocationConsumer: Missing lat/lng in data")
                return

            # Save location to database
            saved = await self._save_bus_location(self.bus_id, lat, lng)

            if saved:
                self.sequence_number += 1
                logger.info(
                    f"✅ Location saved: bus_id={self.bus_id}, lat={lat}, lng={lng}, seq={self.sequence_number}"
                )

                # ⭐ IMPROVED: On first location update, send "connected" status
                if self.sequence_number == 1:
                    await self.channel_layer.group_send(
                        self.group_name,
                        {
                            "type": "tracking_status",
                            "status": "connected",
                            "message": "Driver started tracking",
                        },
                    )

                # Broadcast to all connected clients
                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        "type": "location_update",
                        "lat": lat,
                        "lng": lng,
                        "is_historical": False,
                        "sequence": self.sequence_number,
                    },
                )
            else:
                logger.error(f"❌ Failed to save location for bus_id={self.bus_id}")

    async def location_update(self, event):
        """Send location update to WebSocket client"""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "location_update",
                    "lat": event.get("lat"),
                    "lng": event.get("lng"),
                    "is_historical": event.get("is_historical", False),
                    "sequence": event.get("sequence", 0),
                }
            )
        )

    async def tracking_status(self, event):
        """Send tracking status update to WebSocket client"""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "tracking_status",
                    "status": event.get("status"),
                    "message": event.get("message"),
                }
            )
        )

    async def seat_update(self, event):
        """Broadcast seat availability updates to connected clients."""
        try:
            await self.send(
                text_data=json.dumps(
                    {
                        "type": "seat_update",
                        "seat_id": event.get("seat_id"),
                        "is_available": event.get("is_available"),
                        "seat_number": event.get("seat_number"),
                        "bus_id": event.get("bus_id"),
                    }
                )
            )
        except Exception as e:
            logger.exception(f"Failed to send seat_update: {e}")

    @database_sync_to_async
    def _save_bus_location(self, bus_id, lat, lng):
        """Save bus location to database"""
        try:
            lat_f = float(lat)
            lng_f = float(lng)

            bus = Bus.objects.filter(id=bus_id).first()
            if not bus:
                logger.error(f"Bus not found: id={bus_id}")
                return False

            MIN_MOVEMENT_METERS = 25
            if bus.current_lat and bus.current_lng:
                import math

                R = 6371000
                phi1 = math.radians(bus.current_lat)
                phi2 = math.radians(lat_f)
                dphi = math.radians(lat_f - bus.current_lat)
                dlambda = math.radians(lng_f - bus.current_lng)
                a = (
                    math.sin(dphi / 2) ** 2
                    + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
                )
                c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                distance_m = R * c

                if distance_m < MIN_MOVEMENT_METERS:
                    logger.debug(f"⏭️ Skipping update - moved only {distance_m:.1f}m")
                    return False

            bus.current_lat = lat_f
            bus.current_lng = lng_f
            from django.utils import timezone
            bus.updated_at = timezone.now()  # Mark when location was last updated
            bus.save(update_fields=["current_lat", "current_lng", "updated_at"])  # Include updated_at

            logger.info(f"Bus {bus.number_plate} location updated: {lat_f}, {lng_f}")

            if bus.driver:
                bus.driver.current_lat = lat_f
                bus.driver.current_lng = lng_f
                bus.driver.save(update_fields=["current_lat", "current_lng"])
                logger.info(f"Driver {bus.driver.user.username} location updated: {lat_f}, {lng_f}")
                try:
                    route=getattr(bus, 'route', None)
                    if route:
                        stops = route.get_stops_list()
                        if stops:
                         import math

                         def haversine(lat1, lon1, lat2, lon2):
                            R = 6371
                            phi1 = math.radians(lat1)
                            phi2 = math.radians(lat2)
                            dphi = math.radians(lat2 - lat1)
                            dlambda = math.radians(lon2 - lon1)
                            a = (
                                math.sin(dphi / 2) ** 2
                                + math.cos(phi1)
                                * math.cos(phi2)
                                * math.sin(dlambda / 2) ** 2
                            )
                            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                            return R * c

                        nearest_idx = min(
                            range(len(stops)),
                            key=lambda i: haversine(
                                lat_f, lng_f, stops[i].latitude, stops[i].longitude
                            ),
                        )
                        bus.nearest_stop_index = nearest_idx

                        dist_km = haversine(
                            lat_f,
                            lng_f,
                            stops[nearest_idx].latitude,
                            stops[nearest_idx].longitude,
                        )
                        avg_speed_kmh = 25
                        eta_seconds = int((dist_km / avg_speed_kmh) * 3600)
                        bus.eta_seconds = max(1, eta_seconds)

                        if bus.eta_smoothed_seconds:
                            alpha = 0.3
                            bus.eta_smoothed_seconds = (
                                alpha * bus.eta_seconds
                                + (1 - alpha) * bus.eta_smoothed_seconds
                            )
                        else:
                            bus.eta_smoothed_seconds = float(bus.eta_seconds)

                        bus.save(
                            update_fields=[
                                "nearest_stop_index",
                                "eta_seconds",
                                "eta_smoothed_seconds",
                            ]
                        )
                        logger.info(
                            f"Bus nearest stop: index={nearest_idx}, ETA={bus.eta_seconds}s"
                        )
                except Exception as e:
                 logger.exception(f"Error calculating nearest stop: {e}")

            return True

        except Exception as e:
            logger.exception(f"Error saving bus location: {e}")
            return False

    @database_sync_to_async
    def _clear_bus_location(self, bus_id):
        """Clear bus location when driver stops tracking"""
        try:
            bus = Bus.objects.filter(id=bus_id).first()
            if not bus:
                logger.warning(f"Bus not found for clearing: id={bus_id}")
                return False

            # Clear bus coordinates
            bus.current_lat = None
            bus.current_lng = None
            bus.nearest_stop_index = None
            bus.eta_seconds = None
            bus.eta_smoothed_seconds = None
            bus.save(
                update_fields=[
                    "current_lat",
                    "current_lng",
                    "nearest_stop_index",
                    "eta_seconds",
                    "eta_smoothed_seconds",
                ]
            )
            logger.info(
                f"✅ Cleared location for bus {bus.number_plate} (driver stopped tracking)"
            )

            # Also clear driver coordinates
            if bus.driver:
                bus.driver.current_lat = None
                bus.driver.current_lng = None
                bus.driver.save(update_fields=["current_lat", "current_lng"])
                logger.info(
                    f"✅ Cleared location for driver {bus.driver.user.username}"
                )

            return True

        except Exception as e:
            logger.exception(f"Error clearing bus location: {e}")
            return False


class ChatConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for chat between users and drivers."""

    async def connect(self):
        self.room_name = self.scope["url_route"]["kwargs"].get("room_name")

        # Add legacy chat room subscription
        if self.room_name:
            try:
                await self.channel_layer.group_add(
                    f"chat_{self.room_name}", self.channel_name
                )
            except Exception:
                logger.exception(
                    "Failed to add to legacy chat group chat_%s", self.room_name
                )

        user = self.scope.get("user")
        if user and getattr(user, "is_authenticated", False):
            # Subscribe to personal group depending on role
            try:
                is_driver = await database_sync_to_async(
                    lambda uid: Driver.objects.filter(user__id=uid).exists()
                )(user.id)

                connected_via_legacy_user_room = False
                if self.room_name and str(self.room_name).startswith("user_"):
                    connected_via_legacy_user_room = True

                if is_driver:
                    await self.channel_layer.group_add(
                        f"driver_{user.id}", self.channel_name
                    )
                else:
                    if not connected_via_legacy_user_room:
                        await self.channel_layer.group_add(
                            f"user_{user.id}", self.channel_name
                        )
                    else:
                        logger.info(
                            "ChatConsumer: user %s connected via legacy room %s",
                            user.id,
                            self.room_name,
                        )
            except Exception:
                logger.exception(
                    "Failed to add user %s to personal group", getattr(user, "id", None)
                )

        await self.accept()
        logger.info(
            "ChatConsumer.connect: user_id=%s room_name=%s",
            getattr(user, "id", None),
            self.room_name,
        )

    async def disconnect(self, close_code):
        if self.room_name:
            try:
                await self.channel_layer.group_discard(
                    f"chat_{self.room_name}", self.channel_name
                )
            except Exception:
                pass

        user = self.scope.get("user")
        logger.info(
            "ChatConsumer.disconnect: user_id=%s room_name=%s code=%s",
            getattr(user, "id", None),
            self.room_name,
            close_code,
        )

        if user and getattr(user, "is_authenticated", False):
            try:
                if hasattr(user, "driver_profile"):
                    await self.channel_layer.group_discard(
                        f"driver_{user.id}", self.channel_name
                    )
                else:
                    await self.channel_layer.group_discard(
                        f"user_{user.id}", self.channel_name
                    )
            except Exception:
                pass

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return

        try:
            data = json.loads(text_data)
        except Exception:
            return

        logger.info(
            "ChatConsumer.receive: user=%s data=%s",
            getattr(self.scope.get("user"), "id", None),
            data,
        )

        msg_type = data.get("type")
        if msg_type != "chat_message":
            return

        sender = (
            self.scope.get("user")
            if self.scope.get("user") and self.scope.get("user").is_authenticated
            else None
        )
        if not sender:
            return

        content = data.get("content")
        recipient_id = data.get("recipient_id")
        bus_id = data.get("bus_id")

        # Resolve recipient from bus if not provided
        if not recipient_id and bus_id:
            try:
                is_sender_driver = await database_sync_to_async(
                    lambda uid: Driver.objects.filter(user__id=uid).exists()
                )(sender.id)

                if not is_sender_driver:
                    bus_obj = await database_sync_to_async(
                        Bus.objects.select_related("driver__user").get
                    )(id=bus_id)
                    if bus_obj and bus_obj.driver and bus_obj.driver.user:
                        recipient_id = bus_obj.driver.user.id
                        logger.info(
                            "ChatConsumer.resolved_recipient_from_bus: sender=%s bus=%s recipient=%s",
                            sender.id,
                            bus_id,
                            recipient_id,
                        )
                else:
                    logger.info(
                        "ChatConsumer.skipping_bus_resolution_for_driver_sender=%s",
                        sender.id,
                    )
            except Exception:
                recipient_id = None

        # If still no recipient and sender is a driver, try last contact
        if not recipient_id:
            try:
                is_sender_driver = await database_sync_to_async(
                    lambda uid: Driver.objects.filter(user__id=uid).exists()
                )(sender.id)

                if is_sender_driver:

                    def _get_last_user_to_driver(sid):
                        last = (
                            Message.objects.filter(recipient__id=sid)
                            .exclude(sender__id=sid)
                            .order_by("-created_at")
                            .first()
                        )
                        return last.sender.id if last else None

                    last_user = await database_sync_to_async(_get_last_user_to_driver)(
                        sender.id
                    )
                    if last_user:
                        recipient_id = last_user
                        logger.info(
                            "ChatConsumer resolved recipient for driver %s -> user %s",
                            sender.id,
                            recipient_id,
                        )
            except Exception:
                pass

        if not recipient_id or not content:
            return

        # Persist the message
        await self._create_message(sender.id, recipient_id, bus_id, content)

        sender_name = getattr(sender, "username", None)
        payload = {
            "type": "chat_message",
            "sender_id": sender.id,
            "sender_name": sender_name,
            "recipient_id": recipient_id,
            "content": content,
            "bus_id": bus_id,
        }

        # Forward to recipient personal group
        try:
            await self.channel_layer.group_send(
                f"user_{recipient_id}",
                {
                    "type": "chat_message_forward",
                    **payload,
                },
            )
            logger.info("ChatConsumer.forwarded to user_%s", recipient_id)
        except Exception:
            logger.exception("Failed to forward chat to user_%s", recipient_id)

        # Forward to legacy chat room
        try:
            legacy_room = f"chat_user_{recipient_id}_driver_{sender.id}"
            await self.channel_layer.group_send(
                legacy_room,
                {
                    "type": "chat_message_forward",
                    **payload,
                },
            )
            logger.info("ChatConsumer.forwarded to legacy %s", legacy_room)
        except Exception:
            logger.exception(
                "Failed to forward to legacy room for recipient %s", recipient_id
            )

        # Forward to driver group if recipient is driver
        try:
            if recipient_id != sender.id:
                await self.channel_layer.group_send(
                    f"driver_{recipient_id}",
                    {
                        "type": "chat_message_forward",
                        **payload,
                    },
                )
                logger.info("ChatConsumer.forwarded to driver_%s", recipient_id)
            else:
                logger.info(
                    "ChatConsumer.skipped_driver_forward_to_self for %s", recipient_id
                )
        except Exception:
            logger.exception("ChatConsumer.failed_forward_driver_%s", recipient_id)

        # Echo back to sender
        try:
            is_sender_driver = await database_sync_to_async(
                lambda uid: Driver.objects.filter(user__id=uid).exists()
            )(sender.id)

            if is_sender_driver:
                await self.channel_layer.group_send(
                    f"driver_{sender.id}",
                    {
                        "type": "chat_message_forward",
                        **payload,
                    },
                )
            else:
                await self.channel_layer.group_send(
                    f"user_{sender.id}",
                    {
                        "type": "chat_message_forward",
                        **payload,
                    },
                )

                # Legacy echo
                try:
                    legacy_echo = f"chat_user_{sender.id}_driver_{recipient_id}"
                    await self.channel_layer.group_send(
                        legacy_echo,
                        {
                            "type": "chat_message_forward",
                            **payload,
                        },
                    )
                    logger.info(
                        "ChatConsumer.echoed to legacy %s for sender %s",
                        legacy_echo,
                        sender.id,
                    )
                except Exception:
                    logger.exception(
                        "ChatConsumer.failed_legacy_echo for sender %s", sender.id
                    )

            logger.info("ChatConsumer.echoed to sender %s", sender.id)
        except Exception:
            logger.exception("ChatConsumer.failed_echo_sender %s", sender.id)

    async def chat_message_forward(self, event):
        """Forward chat message to WebSocket"""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "chat_message",
                    "sender_id": event.get("sender_id"),
                    "sender_name": event.get("sender_name"),
                    "recipient_id": event.get("recipient_id"),
                    "content": event.get("content"),
                    "bus_id": event.get("bus_id"),
                }
            )
        )

    async def chat_message(self, event):
        """Backwards-compatible handler for legacy events"""
        await self.chat_message_forward(event)

    async def pickup_notification(self, event):
        """Send pickup notification to driver"""
        pickup_id = event.get("pickup_id")
        await self.send(
            text_data=json.dumps(
                {
                    "type": "pickup_notification",
                    "pickup_id": pickup_id,
                    "user_id": event.get("user_id"),
                    "bus_id": event.get("bus_id"),
                    "stop": event.get("stop"),
                    "message": event.get("message"),
                }
            )
        )

        # Mark as seen
        try:
            if pickup_id:
                await database_sync_to_async(self._mark_pickup_seen)(pickup_id)
        except Exception:
            pass

    @database_sync_to_async
    def _create_message(self, sender_id, recipient_id, bus_id, content):
        """Create message in database"""
        try:
            sender = User.objects.get(id=sender_id)
            recipient = User.objects.get(id=recipient_id)
            bus = Bus.objects.filter(id=bus_id).first() if bus_id else None
            return Message.objects.create(
                sender=sender, recipient=recipient, bus=bus, content=content
            )
        except Exception:
            return None

    def _mark_pickup_seen(self, pickup_id):
        """Mark pickup request as seen by driver"""
        try:
            p = PickupRequest.objects.filter(id=pickup_id).first()
            if p:
                p.seen_by_driver = True
                p.save(update_fields=["seen_by_driver"])
                return True
        except Exception:
            return False

    async def pickup_request_canceled(self, event):
        """Handle pickup request cancellation"""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "pickup_request_canceled",
                    "pickup_id": event.get("pickup_id"),
                    "user_id": event.get("user_id"),
                    "message": event.get("message", "Pickup request canceled"),
                }
            )
        )

    async def reservation_canceled(self, event):
        """Handle reservation cancellation"""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "reservation_canceled",
                    "pickup_id": event.get("pickup_id"),
                    "seat_number": event.get("seat_number"),
                    "user_id": event.get("user_id"),
                    "message": event.get("message", "Reservation canceled"),
                }
            )
        )

    async def seat_reservation_confirmed(self, event):
        """Handle seat reservation confirmation"""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "seat_reservation_confirmed",
                    "pickup_id": event.get("pickup_id"),
                    "seat_number": event.get("seat_number"),
                    "bus_id": event.get("bus_id"),
                    "message": event.get("message", "Seat reserved"),
                }
            )
        )
