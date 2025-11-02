from django.db import models
from django.contrib.auth.models import User
import os
import math

class Stop(models.Model):
    name = models.CharField(max_length=100, unique=True)
    latitude = models.FloatField()
    longitude = models.FloatField()

    def __str__(self):
        return self.name


class Driver(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='driver_profile')
    phone = models.CharField(max_length=15)
    vehicle_number = models.CharField(max_length=20)
    verified = models.BooleanField(default=False)
    current_lat = models.FloatField(null=True, blank=True)
    current_lng = models.FloatField(null=True, blank=True)

    def __str__(self):
        return self.user.username


# New model for vehicle documents
def vehicle_document_upload_path(instance, filename):
    return os.path.join('vehicle_documents', f'driver_{instance.driver.id}', filename)

class VehicleDocument(models.Model):
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name='vehicle_documents')
    document = models.FileField(upload_to=vehicle_document_upload_path)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.driver.user.username} - {os.path.basename(self.document.name)}"


class Bus(models.Model):
    number_plate = models.CharField(max_length=50)
    total_seats = models.PositiveIntegerField(default=25)
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name='buses')
    route = models.ForeignKey('BusRoute', on_delete=models.PROTECT, related_name='buses')
    # Live location fields (optional)
    current_lat = models.FloatField(null=True, blank=True)
    current_lng = models.FloatField(null=True, blank=True)
    # ETA smoothing / state fields (for server-side heuristics)
    eta_seconds = models.IntegerField(null=True, blank=True)
    eta_smoothed_seconds = models.FloatField(null=True, blank=True)
    eta_passed_counter = models.IntegerField(default=0)
    eta_updated_at = models.DateTimeField(null=True, blank=True)
    # Persisted nearest stop index along route (fast checks)
    nearest_stop_index = models.IntegerField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    def __str__(self):
        return f"{self.number_plate} ({self.total_seats} seats)"

    def create_seats(self):
        # Create seats if not already created
        if not self.seats.exists():
            for i in range(1, self.total_seats + 1):
                Seat.objects.create(bus=self, seat_number=i)


class Seat(models.Model):
    bus = models.ForeignKey(Bus, on_delete=models.CASCADE, related_name='seats')
    seat_number = models.PositiveIntegerField()
    is_available = models.BooleanField(default=True)

    def __str__(self):
        return f"Bus {self.bus.number_plate} - Seat {self.seat_number}"


# Through model to maintain order of stops in a route
class RouteStop(models.Model):
    route = models.ForeignKey('BusRoute', on_delete=models.CASCADE)
    stop = models.ForeignKey('Stop', on_delete=models.CASCADE)
    order = models.PositiveIntegerField()
    # optional: distance to next stop in meters
    distance_to_next_m = models.FloatField(
        null=True, 
        blank=True,
        help_text="Distance in meters from this stop to the next stop in route"
    )

    class Meta:
        unique_together = ('route', 'stop')
        ordering = ['order']

    def __str__(self):
        return f"{self.route.name} - {self.stop.name} ({self.order})"

class BusRoute(models.Model):
    name = models.CharField(max_length=100, unique=True)
    stops = models.ManyToManyField('Stop', through='RouteStop', related_name='routes')
    is_active = models.BooleanField(default=False)
    # Optional polyline geometry for route-aware ETA (GeoJSON or encoded polyline)
    polyline = models.TextField(null=True, blank=True)
    route_length_m = models.FloatField(null=True, blank=True)

  # ⭐ ADD THIS NEW FIELD ⭐
    reverse_route = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='forward_route',
        help_text="The reverse direction of this route"
    )
    def get_stops_list(self):
        return [rs.stop for rs in self.routestop_set.order_by('order')]

    def __str__(self):
        return self.name
    
    def get_route_coordinates(self):
        """Return list of [lat, lng] for drawing route on map"""
        stops = self.get_stops_list()
        return [[stop.latitude, stop.longitude] for stop in stops]
    
    def get_stop_graph(self):
        """Build graph for Dijkstra: {stop_id: [(neighbor_id, distance), ...]}"""
        graph = {}
        route_stops = self.routestop_set.order_by('order')
        stops_list = list(route_stops)

        for i, rs in enumerate(stops_list):
            graph[rs.stop.id] = []
        
        # Connect to next stop
            if i < len(stops_list) - 1:
                next_rs = stops_list[i + 1]
            
            # Use stored distance or calculate
                distance = rs.distance_to_next_m
                if distance is None or distance == 0:
                     distance = self._calculate_distance(
                         rs.stop.latitude, rs.stop.longitude,
                         next_rs.stop.latitude, next_rs.stop.longitude
                    )
            
                graph[rs.stop.id].append((next_rs.stop.id, distance))
    
        return graph

    @staticmethod
    def _calculate_distance(lat1, lon1, lat2, lon2):
        """Calculate distance between two points using Haversine formula (returns meters)"""
    
        R = 6371000  # Earth radius in meters
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c


class Bookmark(models.Model):
    """A bookmark created by a user for a specific bus."""
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='bookmarks')
    bus = models.ForeignKey(Bus, on_delete=models.CASCADE, related_name='bookmarks')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'bus')

    def __str__(self):
        return f"{self.user.username} -> {self.bus.number_plate}"


class PickupRequest(models.Model):
    """A user's pickup request/notification to a driver for a bus."""
    STATUS_PENDING = 'pending'
    STATUS_ACK = 'acknowledged'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_ACK, 'Acknowledged'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='pickup_requests')
    bus = models.ForeignKey(Bus, on_delete=models.CASCADE, related_name='pickup_requests')
    stop = models.CharField(max_length=255)
    message = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    seen_by_driver = models.BooleanField(default=False)

    def __str__(self):
        return f"PickupRequest({self.user.username} -> {self.bus.number_plate} @ {self.stop})"


class Message(models.Model):
    """Simple chat message between user and driver (both are User objects).

    Message.sender is the Django User who sent the message. recipient is the target User.
    Optionally associated with a bus.
    """
    sender = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='sent_messages')
    recipient = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='received_messages')
    bus = models.ForeignKey(Bus, on_delete=models.CASCADE, related_name='messages', null=True, blank=True)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    read = models.BooleanField(default=False)

    def __str__(self):
        return f"Message({self.sender.username} -> {self.recipient.username})"

import random
from datetime import timedelta
from django.utils import timezone

class EmailOTP(models.Model):
    """Store OTP codes for email verification"""
    email = models.EmailField()
    otp_code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False)
    
    def is_expired(self):
        """Check if OTP is expired (10 minutes)"""
        from django.conf import settings
        expiry_time = self.created_at + timedelta(minutes=getattr(settings, 'OTP_EXPIRY_MINUTES', 10))
        return timezone.now() > expiry_time
    
    @staticmethod
    def generate_otp():
        """Generate random 6-digit OTP"""
        return str(random.randint(100000, 999999))
    
    def __str__(self):
           return f"{self.email} - {self.otp_code}"
