from .forms import DriverRegisterForm
from .models import VehicleDocument, Bus, BusRoute, EmailOTP
from .utils import send_otp_email
from django.core.mail import send_mail
import json

def driver_register(request):
    if request.method == 'POST':
        # Check if this is OTP verification step
        if 'verify_otp' in request.POST:
            return verify_driver_otp(request)
        
        # Step 1: Send OTP
        form = DriverRegisterForm(request.POST, request.FILES)
        if form.is_valid():
            email = request.POST.get('email')
            
            # Check if email already exists
            if User.objects.filter(email=email).exists():
                messages.error(request, 'Email already registered.')
                return redirect('driver_register')
            
            # Generate and send OTP
            otp_code = EmailOTP.generate_otp()
            
            # Delete old OTPs for this email
            EmailOTP.objects.filter(email=email).delete()
            
            # Create new OTP
            EmailOTP.objects.create(email=email, otp_code=otp_code)
            
            # Send email
            if send_otp_email(email, otp_code):
                # Store form data in session
                request.session['driver_registration_data'] = {
                    'username': request.POST.get('username'),
                    'email': email,
                    'password': request.POST.get('password'),
                    'phone': request.POST.get('phone'),
                    'vehicle_number': request.POST.get('vehicle_number'),
                    'route_id': request.POST.get('route'),
                    'total_seats': request.POST.get('total_seats'),
                }
                
                messages.success(request, f'Verification code sent to {email}. Please check your inbox.')
                return render(request, 'registration/driver_verify_otp.html', {'email': email})
            else:
                messages.error(request, 'Failed to send verification email. Please try again.')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = DriverRegisterForm()
    
    # Get all active routes for the dropdown
        routes = BusRoute.objects.filter(is_active=True)

    return render(request, 'registration/driver_register.html', {
    'form': form,
    'routes': routes
            })


def verify_driver_otp(request):
    """Verify OTP and complete registration"""
    entered_otp = request.POST.get('otp_code', '').strip()
    registration_data = request.session.get('driver_registration_data')
    
    if not registration_data:
        messages.error(request, 'Session expired. Please register again.')
        return redirect('driver_register')
    
    email = registration_data['email']
    
    # Get OTP from database
    try:
        otp_record = EmailOTP.objects.filter(email=email, is_verified=False).latest('created_at')
    except EmailOTP.DoesNotExist:
        messages.error(request, 'Invalid or expired OTP. Please register again.')
        return redirect('driver_register')
    
    # Check if OTP is expired
    if otp_record.is_expired():
        messages.error(request, 'OTP has expired. Please register again.')
        return redirect('driver_register')
    
    # Verify OTP
    if otp_record.otp_code != entered_otp:
        messages.error(request, 'Invalid OTP. Please try again.')
        return render(request, 'registration/driver_verify_otp.html', {'email': email})
    
    # OTP is correct - Complete registration
    try:
        # Create user
        user = User.objects.create_user(
            username=registration_data['username'],
            email=registration_data['email'],
            password=registration_data['password']
        )
        
        # Create driver
        driver = Driver.objects.create(
            user=user,
            phone=registration_data['phone'],
            vehicle_number=registration_data['vehicle_number']
        )
        
        # Handle vehicle documents (if any were uploaded)
        files = request.FILES.getlist('vehicle_documents')
        for f in files:
            VehicleDocument.objects.create(driver=driver, document=f)
        
        # Create bus
        route = BusRoute.objects.get(id=registration_data['route_id'])
        bus = Bus.objects.create(
            number_plate=driver.vehicle_number,
            total_seats=int(registration_data['total_seats']),
            driver=driver,
            route=route
        )
        bus.create_seats()
        
        # Mark OTP as verified
        otp_record.is_verified = True
        otp_record.save()
        
        # Clear session data
        del request.session['driver_registration_data']
        
        messages.success(request, 'Email verified! Registration successful. You can now login.')
        return redirect('driver_login')
        
    except Exception as e:
        messages.error(request, f'Registration failed: {str(e)}')
        return redirect('driver_register')


def driver_forgot_password(request):
    """Driver forgot password - send OTP"""
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        
        if not email:
            messages.error(request, 'Please enter your email address.')
            return redirect('driver_forgot_password')
        
        # Check if email exists and belongs to a driver
        try:
            user = User.objects.get(email=email)
            if not hasattr(user, 'driver_profile'):
                messages.error(request, 'No driver account found with this email.')
                return redirect('driver_forgot_password')
        except User.DoesNotExist:
            messages.error(request, 'No account found with this email.')
            return redirect('driver_forgot_password')
        
        # Generate and send OTP
        otp_code = EmailOTP.generate_otp()
        
        # Delete old OTPs for this email
        EmailOTP.objects.filter(email=email).delete()
        
        # Create new OTP
        EmailOTP.objects.create(email=email, otp_code=otp_code)
        
        # Send email with different message
        subject = 'Smart Transport - Password Reset Code'
        message = f'''
Hello {user.username},

You requested to reset your password for your Smart Transport driver account.

Your password reset code is:

{otp_code}

This code will expire in 10 minutes.

If you didn't request this, please ignore this email and your password will remain unchanged.

Best regards,
Smart Transport Team
        '''
        
        try:
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False,
            )
            
            # Store email in session
            request.session['reset_password_email'] = email
            
            messages.success(request, f'Password reset code sent to {email}')
            return render(request, 'registration/driver_reset_otp.html', {'email': email})
            
        except Exception as e:
            messages.error(request, 'Failed to send email. Please try again.')
            return redirect('driver_forgot_password')
    
    return render(request, 'registration/driver_forgot_password.html')


def driver_verify_reset_otp(request):
    """Verify OTP for password reset"""
    if request.method == 'POST':
        entered_otp = request.POST.get('otp_code', '').strip()
        email = request.session.get('reset_password_email')
        
        if not email:
            messages.error(request, 'Session expired. Please try again.')
            return redirect('driver_forgot_password')
        
        # Get OTP from database
        try:
            otp_record = EmailOTP.objects.filter(email=email, is_verified=False).latest('created_at')
        except EmailOTP.DoesNotExist:
            messages.error(request, 'Invalid or expired OTP.')
            return redirect('driver_forgot_password')
        
        # Check if OTP is expired
        if otp_record.is_expired():
            messages.error(request, 'OTP has expired. Please request a new one.')
            return redirect('driver_forgot_password')
        
        # Verify OTP
        if otp_record.otp_code != entered_otp:
            messages.error(request, 'Invalid OTP. Please try again.')
            return render(request, 'registration/driver_reset_otp.html', {'email': email})
        
        # OTP is correct - Mark as verified and show new password form
        otp_record.is_verified = True
        otp_record.save()
        
        return render(request, 'registration/driver_new_password.html', {'email': email})
    
    return redirect('driver_forgot_password')


def driver_set_new_password(request):
    """Set new password after OTP verification"""
    if request.method == 'POST':
        email = request.session.get('reset_password_email')
        new_password = request.POST.get('new_password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()
        
        if not email:
            messages.error(request, 'Session expired. Please try again.')
            return redirect('driver_forgot_password')
        
        # Validation
        if not new_password or not confirm_password:
            messages.error(request, 'Both password fields are required.')
            return render(request, 'registration/driver_new_password.html', {'email': email})
        
        if new_password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'registration/driver_new_password.html', {'email': email})
        
        if len(new_password) < 6:
            messages.error(request, 'Password must be at least 6 characters long.')
            return render(request, 'registration/driver_new_password.html', {'email': email})
        
        # Verify that OTP was verified for this email
        verified_otp = EmailOTP.objects.filter(email=email, is_verified=True).exists()
        if not verified_otp:
            messages.error(request, 'Invalid request. Please verify OTP first.')
            return redirect('driver_forgot_password')
        
        # Update password
        try:
            user = User.objects.get(email=email)
            user.set_password(new_password)
            user.save()
            
            # Clear session
            del request.session['reset_password_email']
            
            messages.success(request, 'Password changed successfully! You can now login with your new password.')
            return redirect('driver_login')
            
        except User.DoesNotExist:
            messages.error(request, 'User not found.')
            return redirect('driver_forgot_password')
    
    return redirect('driver_forgot_password')

from django.views.decorators.csrf import csrf_exempt
import json
import logging
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q
from .models import BusRoute, Driver, Bus, Seat, Stop
from .models import Bookmark, PickupRequest, Message
from django.views.decorators.http import require_POST
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings

logger = logging.getLogger(__name__)

# Use settings or default values
STOP_DELAY_SECONDS = getattr(settings, 'STOP_DELAY_SECONDS', 60)
avg_speed_kmh = getattr(settings, 'AVG_BUS_SPEED_KMH', 25)
def homepage(request):
    from .dsa import dijkstra
    import math
    import logging

    logger = logging.getLogger(__name__)

    # Collect stops from all bus routes
    stops = set()
    routes = BusRoute.objects.filter(is_active=True)
    for route in routes:
        stops.update(route.get_stops_list())
    stops = sorted(list(stops), key=lambda stop: stop.name)

    buses_info = []
    raw_pickup = request.GET.get('pickup', '').strip() if 'pickup' in request.GET else ''
    raw_destination = request.GET.get('destination', '').strip() if 'destination' in request.GET else ''
    pickup_id = None
    destination_id = None

    # Parse pickup/destination IDs
    try:
        if raw_pickup:
            pickup_id = int(raw_pickup)
    except Exception:
        pickup_id = None
    try:
        if raw_destination:
            destination_id = int(raw_destination)
    except Exception:
        destination_id = None

    # Resolve by name if ID parsing failed
    if pickup_id is None and raw_pickup:
        s = Stop.objects.filter(name__iexact=raw_pickup).first()
        if s:
            pickup_id = s.id
    if destination_id is None and raw_destination:
        s2 = Stop.objects.filter(name__iexact=raw_destination).first()
        if s2:
            destination_id = s2.id

    show_passed = request.GET.get('show_passed', '0') == '1'

    # Haversine distance function
    def haversine(lat1, lon1, lat2, lon2):
        R = 6371  # Earth radius in km
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    if pickup_id and destination_id:
        logger.info(f"Searching buses from pickup {pickup_id} to destination {destination_id}")

        # Find all routes containing both stops
        matching_routes = []
        for route in routes:
            stops_objs = route.get_stops_list()

            if not stops_objs:
                logger.warning(f"Route {route.name} has no stops!")
                continue

            stops_ids = [s.id for s in stops_objs]

            if pickup_id in stops_ids and destination_id in stops_ids:
                pickup_idx = stops_ids.index(pickup_id)
                dest_idx = stops_ids.index(destination_id)

                # Only include if pickup comes before destination
                if pickup_idx < dest_idx:
                    logger.info(f"Route {route.name} matches: pickup at index {pickup_idx}, dest at {dest_idx}")
                    matching_routes.append((route, pickup_idx, dest_idx, stops_objs))
                else:
                    logger.info(f"Route {route.name} rejected: wrong order (pickup={pickup_idx}, dest={dest_idx})")

        logger.info(f"Found {len(matching_routes)} matching routes")

        # Calculate ETA for each bus using Dijkstra
        for route, pickup_idx, dest_idx, stops_objs in matching_routes:
            bus = route.buses.first()
            if not bus:
                continue

            logger.info(f"\n--- Processing Bus {bus.number_plate} on Route {route.name} ---")

            available_seats = bus.seats.filter(is_available=True).count()

            # Get bus location
            bus_lat = getattr(bus, 'current_lat', None)
            bus_lng = getattr(bus, 'current_lng', None)

            logger.info(f"Bus GPS: lat={bus_lat}, lng={bus_lng}")
            from django.utils import timezone
            from datetime import timedelta

            is_stale = False
            if hasattr(bus, 'updated_at') and bus.updated_at:
                time_since_update = timezone.now() - bus.updated_at
                if time_since_update > timedelta(minutes=5):
                    is_stale = True
                    logger.warning(
                        f"⏰ Bus {bus.number_plate} GPS data is STALE "
                        f"(last update: {time_since_update.seconds//60} minutes ago)"
                    )

            # ⭐ CRITICAL FIX: If no live GPS data, mark as no_location and skip ETA calculation
            # This prevents showing fake ETA when driver hasn't started tracking
            if bus_lat is None or bus_lng is None or is_stale:
                if is_stale:
                    logger.warning(
                        f"❌ Bus {bus.id} GPS data STALE! Driver stopped tracking."
                    )
                else:
                    logger.warning(f"❌ Bus {bus.id} has NO GPS! Driver not tracking.")
                
                buses_info.append({
                    'route': route,
                    'bus': bus,
                    'eta': None,
                    'available_seats': available_seats,
                    'status': 'no_location',  # This will show "Driver not tracking yet" in template
                    'nearest_stop': None,
                    'stops_between': None,
                })
                continue  # Skip to next bus - don't calculate fake ETA!

            # Calculate ETA using Dijkstra (only if we have real GPS data)
            eta = None
            status = 'unknown'
            nearest_stop = None
            stops_between = 0

            try:
                # Build route graph
                graph = route.get_stop_graph()
                logger.info(f"🔍 Graph keys: {list(graph.keys())[:5]}...")
                logger.info(f"🔍 Graph has {len(graph)} stops")

                if not graph:
                    logger.error(f"Empty graph for route {route.name}")
                    raise Exception("Empty graph")

                # Find nearest stop to bus
                nearest_stop_idx = min(
                    range(len(stops_objs)), 
                    key=lambda i: haversine(bus_lat, bus_lng, stops_objs[i].latitude, stops_objs[i].longitude)
                )
                nearest_stop = stops_objs[nearest_stop_idx]
                nearest_stop_id = nearest_stop.id

                logger.info(f"🔍 Nearest stop: {nearest_stop.name} (ID: {nearest_stop_id}, Index: {nearest_stop_idx})")
                logger.info(f"🔍 Pickup stop: {stops_objs[pickup_idx].name} (ID: {stops_objs[pickup_idx].id}, Index: {pickup_idx})")
                logger.info(f"🔍 Destination stop: {stops_objs[dest_idx].name} (ID: {stops_objs[dest_idx].id}, Index: {dest_idx})")

                from .routing_api import get_road_distance_with_fallback
                dist_to_nearest, is_road = get_road_distance_with_fallback(
                    bus_lat, bus_lng,
                    nearest_stop.latitude, nearest_stop.longitude
)
                distance_type = "🛣️ ROAD" if is_road else "📏 ESTIMATED"
                logger.info(f"Nearest stop: {nearest_stop.name} (index {nearest_stop_idx}), distance: {dist_to_nearest:.2f} km ({distance_type})")

                # Check if bus already passed pickup
                if nearest_stop_idx > pickup_idx:
                    logger.warning(f"Bus already PASSED pickup!")
                    status = 'passed'
                    eta = None
                else:
                    # Use Dijkstra to find distance along route
                    pickup_stop_id = stops_objs[pickup_idx].id

                    if nearest_stop_id == pickup_stop_id:
                        logger.info(f"🎯 Bus is AT pickup stop! Using direct distance")

                        dist_bus_to_pickup_km, is_road = get_road_distance_with_fallback(
                            bus_lat, bus_lng,
                            stops_objs[pickup_idx].latitude, stops_objs[pickup_idx].longitude
                        )
                        total_distance_km = dist_bus_to_pickup_km
                        stops_between = 0

                        distance_type = "🛣️ ROAD" if is_road else "📏 ESTIMATED"
                        logger.info(f"   Direct distance to pickup: {total_distance_km:.2f} km ({distance_type})")
                    else:    
                        logger.info(f"Running Dijkstra from {nearest_stop_id} to {pickup_stop_id}")
                        dist_along_route_meters, path = dijkstra(graph, nearest_stop_id, pickup_stop_id)

                        logger.info(f"Dijkstra result: distance={dist_along_route_meters}m")

                        if dist_along_route_meters != float('inf') and dist_along_route_meters >= 0:
                            # Convert bus-to-nearest distance to meters
                            dist_bus_to_nearest_km = dist_to_nearest 

                            # Total distance calculation
                            dist_along_route_km = dist_along_route_meters / 1000.0
                            total_distance_km = dist_bus_to_nearest_km + dist_along_route_km

                            # Calculate stop delay
                            stops_between = pickup_idx - nearest_stop_idx
                            if stops_between < 0:
                                stops_between = 0

                                logger.info(f"   - Distance bus→nearest: {dist_bus_to_nearest_km:.2f} km")
                                logger.info(f"   - Distance along route: {dist_along_route_km:.2f} km")
                        else:
                            eta =None
                            status = 'no_route'
                            logger.error("❌ No valid route found")
                            continue

                        # Each stop adds delay (boarding/alighting time)
                    STOP_DELAY_SECONDS = 60  # 1 minute per stop
                    total_stop_delay_seconds = stops_between * STOP_DELAY_SECONDS
                    total_stop_delay_minutes = total_stop_delay_seconds / 60.0

                    # Average speed in city traffic (km/h)
                    avg_speed_kmh = 25

                    # Calculate base travel time (without stops)
                    travel_time_hours = total_distance_km / avg_speed_kmh
                    travel_time_minutes = travel_time_hours * 60

                    # Add stop delay to travel time
                    total_time_minutes = travel_time_minutes + total_stop_delay_minutes
                    eta = max(1, int(total_time_minutes))

                    logger.info(f"✅ ETA CALCULATED: {eta} min")
                    logger.info(f"   - Travel distance: {total_distance_km:.2f} km")
                    logger.info(f"   - Travel time: {travel_time_minutes:.1f} min")
                    logger.info(f"   - Stops between: {stops_between}")
                    logger.info(f"   - Stop delay: {total_stop_delay_minutes:.1f} min")

                    # Determine status based on ETA
                    if eta <= 2:
                        status = 'arriving_soon'
                    elif eta <= 10:
                        status = 'catchable'
                    elif eta <= 30:
                        status = 'far'
                    else:
                        eta = None
                        status = 'no_route'

            except Exception as e:
                logger.error(f"❌ ERROR calculating ETA for bus {bus.number_plate}")
                logger.error(f"❌ Error type: {type(e).__name__}")
                logger.error(f"❌ Error message: {str(e)}")
                logger.exception(f"❌ Full traceback:")
                eta = None
                status = 'error'

            pickup_to_dest_distance_km = None 
            try:
                graph = route.get_stop_graph()
                pickup_stop_id = stops_objs[pickup_idx].id
                dest_stop_id = stops_objs[dest_idx].id

                distance_meters, path = dijkstra(graph, pickup_stop_id, dest_stop_id)

                if distance_meters != float('inf') and distance_meters > 0:
                    pickup_to_dest_distance_km = distance_meters / 1000.0  # Convert to km
                    logger.info(f"📏 Distance from pickup to destination: {pickup_to_dest_distance_km:.2f} km")
                    logger.info(f"📍 Route path: {len(path)} stops")
                else:
                    logger.warning(f"⚠️ Could not calculate distance from pickup to destination")
            except Exception as e:
                logger.error(f"❌ Error calculating pickup-to-dest distance: {e}")
                pickup_to_dest_distance_km = None

            buses_info.append(
                {
                    "route": route,
                    "bus": bus,
                    "eta": eta,
                    "available_seats": available_seats,
                    "status": status,
                    "nearest_stop": nearest_stop.name if nearest_stop else None,
                    "stops_between": stops_between,
                    "pickup_to_dest_distance": pickup_to_dest_distance_km,
                }
            )

        # Sort by ETA (nearest first, None values last)
        buses_info.sort(
            key=lambda x: (
                x.get("pickup_to_dest_distance") is None,  # No distance = last
                x.get("pickup_to_dest_distance")
                or float("inf"),  # Primary: shortest distance
                x.get("eta") is None,  # If equal distance, no ETA = last
                x.get("eta") or 9999,  # Secondary: fastest ETA
            )
        )
        logger.info(
            f"\n🏆 Final results ranked by SHORTEST ROUTE (Dijkstra algorithm):"
        )
        for i, info in enumerate(buses_info):
            dist_str = f"{info.get('pickup_to_dest_distance'):.2f} km" if info.get('pickup_to_dest_distance') else "N/A"
            eta_str = f"{info['eta']} min" if info.get('eta') else "N/A"
            logger.info(f"  Rank {i+1}: {info['bus'].number_plate} - Distance: {dist_str}, ETA: {eta_str}")

        # Filter out passed buses if not showing them
        if not show_passed:
            buses_info = [b for b in buses_info if b.get('status') != 'passed']

    context = {
        'stops': stops,
        'buses_info': buses_info,
        'pickup': raw_pickup,
        'destination': raw_destination,
        'pickup_id': pickup_id,
        'destination_id': destination_id,
        'show_passed': show_passed,
    }
    return render(request, 'user/homepage.html', context)


def driver_login(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(username=username, password=password)
        if user:
            if hasattr(user, 'driver_profile'):
                login(request, user)
                return redirect('driver_dashboard')
            else:
                messages.error(request, 'Not registered as a driver.')
                return redirect('driver_login')
        messages.error(request, 'Invalid credentials.')
        return redirect('driver_login')
    return render(request, 'registration/driver_login.html')


@login_required
def driver_dashboard(request):
    if not hasattr(request.user, 'driver_profile'):
        return redirect('homepage')
    driver = request.user.driver_profile
    bus = driver.buses.first()
    seats = []
    last_row_start = None
    seat_grid_columns = []
    route = bus.route if bus else None
    if bus:
        if request.method == 'POST' and not bus.seats.exists():
            # Create seats if not already created
            total_seats = int(request.POST.get('total_seats', bus.total_seats))
            bus.total_seats = total_seats
            bus.save()
            bus.create_seats()
    seats = list(bus.seats.order_by('seat_number').all())
    # Layout seats with a left-side door gap and 6 columns total:
    # columns: [door-gap, A-window, A-aisle, middle, B-aisle, B-window]
    # Normal rows: 4 seats -> map to columns [2,3,5,6] (col 1 is door gap, col 4 is middle)
    # Final back row: up to 5 seats across columns 2..6 (includes middle single seat)
    last_row_start = bus.total_seats - 5 if bus.total_seats >= 5 else 0
    seats_per_row = 4
    col_map = [2, 3, 5, 6]
    for idx, seat in enumerate(seats):
        if idx < last_row_start:
            row = (idx // seats_per_row) + 1
            pos = idx % seats_per_row
            col = col_map[pos]
        else:
            # final back row: place seats across columns 2..6 (col 1 reserved for door gap)
            row = (last_row_start // seats_per_row) + 1 if last_row_start > 0 else (idx // seats_per_row) + 1
            col = (idx - last_row_start) + 2
            if col < 2:
                col = 2
            if col > 6:
                col = 6
        seat_grid_columns.append((seat, row, col))
    context = {
        'driver': driver,
        'bus': bus,
        'route': route,
        'seats': seats,
        'last_row_start': last_row_start,
        'seat_grid_columns': seat_grid_columns,
        # determine the last user who messaged this driver (for quick load)
        'last_contact_user_id': None,
    }
    try:
        # find last message where recipient is this driver (i.e., a user messaged the driver)
        last_msg = Message.objects.filter(recipient=request.user).exclude(sender=request.user).order_by('-created_at').first()
        if last_msg:
            context['last_contact_user_id'] = last_msg.sender.id
    except Exception:
        # ignore failures
        pass
    return render(request, 'driver/dashboard.html', context)


@login_required
@require_POST
def clear_chat(request, other_user_id):
    # Allow either participant to clear (delete) messages between request.user and other_user_id
    try:
        other = User.objects.get(id=other_user_id)
    except User.DoesNotExist:
        return JsonResponse({'status': 'error', 'error': 'user not found'})
    # Ensure the requester is one of the participants in existing conversation
    # Delete all messages where (sender=request.user and recipient=other) OR (sender=other and recipient=request.user)
    try:
        qs = Message.objects.filter(
            (Q(sender=request.user) & Q(recipient=other)) |
            (Q(sender=other) & Q(recipient=request.user))
        )
        deleted_count, _ = qs.delete()
        return JsonResponse({'status': 'success', 'deleted': deleted_count})
    except Exception as e:
        return JsonResponse({'status': 'error', 'error': str(e)})

@csrf_exempt
def toggle_seat(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            seat_id = data.get('seat_id')
            seat = Seat.objects.get(id=seat_id)
            seat.is_available = not seat.is_available
            seat.save()
            # Notify connected clients (users tracking this bus) about the seat change
            try:
                channel_layer = get_channel_layer()
                payload = {
                    'type': 'seat_update',
                    'seat_id': seat.id,
                    'is_available': seat.is_available,
                    'seat_number': seat.seat_number,
                    'bus_id': seat.bus.id,
                }
                async_to_sync(channel_layer.group_send)(f'bus_{seat.bus.id}', payload)
            except Exception:
                # non-fatal if channels not configured
                logger.exception('Failed to broadcast seat_update for seat %s', seat.id)
            return JsonResponse({'status': 'success', 'is_available': seat.is_available})
        except Exception as e:
            return JsonResponse({'status': 'error', 'error': str(e)})
    return JsonResponse({'status': 'error', 'error': 'Invalid request'})


def update_location(request):
    # This view is used via AJAX to update driver's location.
    if request.method == 'POST' and request.user.is_authenticated and hasattr(request.user, 'driver_profile'):
        lat = request.POST.get('lat')
        lng = request.POST.get('lng')
        try:
            lat_f = float(lat)
            lng_f = float(lng)
        except Exception:
            return JsonResponse({'status': 'error', 'error': 'invalid coordinates'})

        driver = request.user.driver_profile
        driver.current_lat = lat_f
        driver.current_lng = lng_f
        driver.save(update_fields=['current_lat', 'current_lng'])

        # Also persist on the driver's primary bus (if any) so homepage can use persisted nearest_stop_index
        try:
            bus = driver.buses.first()
            if bus:
                # preserve old values for comparison
                old_nearest = bus.nearest_stop_index if bus.nearest_stop_index is not None else None
                old_eta_smoothed = bus.eta_smoothed_seconds if getattr(bus, 'eta_smoothed_seconds', None) is not None else None

                bus.current_lat = lat_f
                bus.current_lng = lng_f

                # compute nearest stop index and ETA seconds if route and stops are available
                try:
                    route = getattr(bus, 'route', None)
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
                                a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
                                c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                                return R * c

                            # find nearest stop index
                            nearest_idx = min(range(len(stops)), key=lambda i: haversine(lat_f, lng_f, stops[i].latitude, stops[i].longitude))
                            bus.nearest_stop_index = int(nearest_idx)

                            # compute ETA_seconds to that nearest stop (as a conservative estimate)
                            dist_km = haversine(lat_f, lng_f, stops[nearest_idx].latitude, stops[nearest_idx].longitude)
                            avg_speed_kmh = getattr(settings, 'AVG_SPEED_KMH', 25)
                            eta_seconds = int((dist_km / avg_speed_kmh) * 3600)
                            if eta_seconds < 1:
                                eta_seconds = 1
                            bus.eta_seconds = int(eta_seconds)

                            # ETA smoothing (exponential moving average)
                            alpha = getattr(settings, 'ETA_SMOOTH_ALPHA', 0.3)
                            if old_eta_smoothed is None:
                                bus.eta_smoothed_seconds = float(bus.eta_seconds)
                            else:
                                bus.eta_smoothed_seconds = float(alpha * float(bus.eta_seconds) + (1 - alpha) * float(old_eta_smoothed))

                            # passed counter: if bus moved forward along route (index increased), increment; if moved backward, reset
                            try:
                                if old_nearest is not None:
                                    if int(nearest_idx) > int(old_nearest):
                                        bus.eta_passed_counter = (getattr(bus, 'eta_passed_counter', 0) or 0) + 1
                                    elif int(nearest_idx) < int(old_nearest):
                                        bus.eta_passed_counter = 0
                            except Exception:
                                # ignore counter failures
                                pass
                except Exception:
                    # non-fatal; continue without nearest index / eta
                    pass

                # save only fields that exist on the model
                save_fields = []
                for f in ['current_lat', 'current_lng', 'nearest_stop_index', 'eta_seconds', 'eta_smoothed_seconds', 'eta_passed_counter']:
                    if hasattr(bus, f):
                        save_fields.append(f)
                if save_fields:
                    bus.save(update_fields=save_fields)
        except Exception:
            # ignore bus persistence failures
            pass

        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'failed'})


def user_login(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(username=username, password=password)
        if user:
            login(request, user)
            return redirect('homepage')
        messages.error(request, 'Invalid credentials.')
        return redirect('user_login')
    return render(request, 'registration/user_login.html')


def user_register(request):
    if request.method == 'POST':
        # Check if this is OTP verification step
        if 'verify_otp' in request.POST:
            return verify_user_otp(request)
        
        # Step 1: Send OTP
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()
        
        # Validation
        if not username or not email or not password:
            messages.error(request, 'All fields are required.')
            return redirect('user_register')
        
        # Check if username already exists
        if User.objects.filter(username=username).exists():
            messages.error(request, 'Username already taken.')
            return redirect('user_register')
        
        # Check if email already exists
        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email already registered.')
            return redirect('user_register')
        
        # Generate and send OTP
        otp_code = EmailOTP.generate_otp()
        
        # Delete old OTPs for this email
        EmailOTP.objects.filter(email=email).delete()
        
        # Create new OTP
        EmailOTP.objects.create(email=email, otp_code=otp_code)
        
        # Send email
        if send_otp_email(email, otp_code):
            # Store form data in session
            request.session['user_registration_data'] = {
                'username': username,
                'email': email,
                'password': password,
            }
            
            messages.success(request, f'Verification code sent to {email}. Please check your inbox.')
            return render(request, 'registration/user_verify_otp.html', {'email': email})
        else:
            messages.error(request, 'Failed to send verification email. Please try again.')
            return redirect('user_register')
    else:
        return render(request, 'registration/user_register.html')


def verify_user_otp(request):
    """Verify OTP and complete user registration"""
    entered_otp = request.POST.get('otp_code', '').strip()
    registration_data = request.session.get('user_registration_data')
    
    if not registration_data:
        messages.error(request, 'Session expired. Please register again.')
        return redirect('user_register')
    
    email = registration_data['email']
    
    # Get OTP from database
    try:
        otp_record = EmailOTP.objects.filter(email=email, is_verified=False).latest('created_at')
    except EmailOTP.DoesNotExist:
        messages.error(request, 'Invalid or expired OTP. Please register again.')
        return redirect('user_register')
    
    # Check if OTP is expired
    if otp_record.is_expired():
        messages.error(request, 'OTP has expired. Please register again.')
        return redirect('user_register')
    
    # Verify OTP
    if otp_record.otp_code != entered_otp:
        messages.error(request, 'Invalid OTP. Please try again.')
        return render(request, 'registration/user_verify_otp.html', {'email': email})
    
    # OTP is correct - Complete registration
    try:
        # Create user
        user = User.objects.create_user(
            username=registration_data['username'],
            email=registration_data['email'],
            password=registration_data['password']
        )
        
        # Mark OTP as verified
        otp_record.is_verified = True
        otp_record.save()
        
        # Clear session data
        del request.session['user_registration_data']
        
        messages.success(request, 'Email verified! Registration successful. You can now login.')
        return redirect('user_login')
        
    except Exception as e:
        messages.error(request, f'Registration failed: {str(e)}')
        return redirect('user_register')

def user_forgot_password(request):
    """User forgot password - send OTP"""
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        
        if not email:
            messages.error(request, 'Please enter your email address.')
            return redirect('user_forgot_password')
        
        # Check if email exists
        try:
            user = User.objects.get(email=email)
            # Check if user has driver profile (drivers should use driver forgot password)
            if hasattr(user, 'driver_profile'):
                messages.error(request, 'This email belongs to a driver account. Please use driver forgot password.')
                return redirect('user_forgot_password')
        except User.DoesNotExist:
            messages.error(request, 'No account found with this email.')
            return redirect('user_forgot_password')
        
        # Generate and send OTP
        otp_code = EmailOTP.generate_otp()
        
        # Delete old OTPs for this email
        EmailOTP.objects.filter(email=email).delete()
        
        # Create new OTP
        EmailOTP.objects.create(email=email, otp_code=otp_code)
        
        # Send email
        if send_otp_email(email, otp_code, purpose='password_reset'):
            # Store email in session
            request.session['user_reset_password_email'] = email
            
            messages.success(request, f'Password reset code sent to {email}')
            return render(request, 'registration/user_reset_otp.html', {'email': email})
        else:
            messages.error(request, 'Failed to send email. Please try again.')
            return redirect('user_forgot_password')
    
    return render(request, 'registration/user_forgot_password.html')


def user_verify_reset_otp(request):
    """Verify OTP for user password reset"""
    if request.method == 'POST':
        entered_otp = request.POST.get('otp_code', '').strip()
        email = request.session.get('user_reset_password_email')
        
        if not email:
            messages.error(request, 'Session expired. Please try again.')
            return redirect('user_forgot_password')
        
        # Get OTP from database
        try:
            otp_record = EmailOTP.objects.filter(email=email, is_verified=False).latest('created_at')
        except EmailOTP.DoesNotExist:
            messages.error(request, 'Invalid or expired OTP.')
            return redirect('user_forgot_password')
        
        # Check if OTP is expired
        if otp_record.is_expired():
            messages.error(request, 'OTP has expired. Please request a new one.')
            return redirect('user_forgot_password')
        
        # Verify OTP
        if otp_record.otp_code != entered_otp:
            messages.error(request, 'Invalid OTP. Please try again.')
            return render(request, 'registration/user_reset_otp.html', {'email': email})
        
        # OTP is correct - Mark as verified and show new password form
        otp_record.is_verified = True
        otp_record.save()
        
        return render(request, 'registration/user_new_password.html', {'email': email})
    
    return redirect('user_forgot_password')


def user_set_new_password(request):
    """Set new password for user after OTP verification"""
    if request.method == 'POST':
        email = request.session.get('user_reset_password_email')
        new_password = request.POST.get('new_password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()
        
        if not email:
            messages.error(request, 'Session expired. Please try again.')
            return redirect('user_forgot_password')
        
        # Validation
        if not new_password or not confirm_password:
            messages.error(request, 'Both password fields are required.')
            return render(request, 'registration/user_new_password.html', {'email': email})
        
        if new_password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'registration/user_new_password.html', {'email': email})
        
        if len(new_password) < 6:
            messages.error(request, 'Password must be at least 6 characters long.')
            return render(request, 'registration/user_new_password.html', {'email': email})
        
        # Verify that OTP was verified for this email
        verified_otp = EmailOTP.objects.filter(email=email, is_verified=True).exists()
        if not verified_otp:
            messages.error(request, 'Invalid request. Please verify OTP first.')
            return redirect('user_forgot_password')
        
        # Update password
        try:
            user = User.objects.get(email=email)
            user.set_password(new_password)
            user.save()
            
            # Clear session
            del request.session['user_reset_password_email']
            
            messages.success(request, 'Password changed successfully! You can now login with your new password.')
            return redirect('user_login')
            
        except User.DoesNotExist:
            messages.error(request, 'User not found.')
            return redirect('user_forgot_password')
    
    return redirect('user_forgot_password')   
def track_bus(request, bus_id):
    # Display live tracking and seat info for the selected bus.
    from .models import Bus
    bus = Bus.objects.filter(id=bus_id).first()
    seats = list(bus.seats.order_by('seat_number').all()) if bus else []
    last_row_start = bus.total_seats - 5 if bus and bus.total_seats >= 5 else 0
    seat_grid_columns = []
    seats_per_row = 4
    # Use left door gap and 6 columns: map normal row seats to columns [2,3,5,6]
    col_map = [2, 3, 5, 6]
    for idx, seat in enumerate(seats):
        if idx < last_row_start:
            row = (idx // seats_per_row) + 1
            pos = idx % seats_per_row
            col = col_map[pos]
        else:
            # final back row uses columns 2..6 (includes middle single seat)
            row = (last_row_start // seats_per_row) + 1 if last_row_start > 0 else (idx // seats_per_row) + 1
            col = (idx - last_row_start) + 2
            if col < 2: col = 2
            if col > 6: col = 6
        seat_grid_columns.append((seat, row, col))
    # Determine if the current user has bookmarked this bus
    is_bookmarked = False
    if request.user.is_authenticated:
        is_bookmarked = Bookmark.objects.filter(user=request.user, bus=bus).exists()

    # Chat room naming: user_<uid>_driver_<did>
    chat_room = None
    if request.user.is_authenticated and bus and bus.driver and bus.driver.user:
        chat_room = f'user_{request.user.id}_driver_{bus.driver.user.id}'

    # allow prefilling pickup stop via query param (e.g., ?pickup=Kathmandu)
    default_pickup = request.GET.get('pickup', '')

    # compute ETA for default pickup if possible
    eta = None
    pickup_coords = None
    if default_pickup and bus:
        try:
            stop_obj = Stop.objects.filter(name__iexact=default_pickup.strip()).first()
            if stop_obj:
                pickup_coords = (stop_obj.latitude, stop_obj.longitude)
            else:
                # try to interpret default_pickup as free text coordinate pair "lat,lng"
                if ',' in default_pickup:
                    parts = default_pickup.split(',')
                    lat = float(parts[0].strip())
                    lng = float(parts[1].strip())
                    pickup_coords = (lat, lng)
        except Exception:
            pickup_coords = None

    if pickup_coords and bus and getattr(bus, 'current_lat', None) is not None and getattr(bus, 'current_lng', None) is not None:
        try:
            import math
            def haversine(lat1, lon1, lat2, lon2):
                R = 6371  # km
                phi1 = math.radians(lat1)
                phi2 = math.radians(lat2)
                dphi = math.radians(lat2 - lat1)
                dlambda = math.radians(lon2 - lon1)
                a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
                c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                return R * c

            # Prefer route-aware ETA if route/stops are available
            route = getattr(bus, 'route', None)
            distance_km = None
            if route:
                try:
                    stops = route.get_stops_list()
                    # find pickup stop object in this route by coordinates match
                    pickup_stop_obj = None
                    for s in stops:
                        if abs(s.latitude - float(pickup_coords[0])) < 1e-6 and abs(s.longitude - float(pickup_coords[1])) < 1e-6:
                            pickup_stop_obj = s
                            break
                    if pickup_stop_obj:
                        # compute distance along route from bus to pickup
                        # find nearest stop index to bus
                        def stop_dist(idx):
                            s = stops[idx]
                            return haversine(bus.current_lat, bus.current_lng, s.latitude, s.longitude)
                        nearest_idx = min(range(len(stops)), key=lambda i: stop_dist(i)) if stops else 0
                        # distance from bus to its nearest stop
                        dist = stop_dist(nearest_idx)
                        # then sum along stops from nearest_idx to pickup index (wrapping)
                        pickup_idx = next((i for i,s in enumerate(stops) if s.id == pickup_stop_obj.id), None)
                        if pickup_idx is None:
                            distance_km = None
                        else:
                            i = nearest_idx
                            while i != pickup_idx:
                                a = stops[i]
                                b = stops[(i+1) % len(stops)]
                                dist += haversine(a.latitude, a.longitude, b.latitude, b.longitude)
                                i = (i+1) % len(stops)
                            distance_km = dist
                except Exception:
                    distance_km = None

            # fallback to straight-line if route-aware not available
            if distance_km is None:
                distance_km = haversine(bus.current_lat, bus.current_lng, pickup_coords[0], pickup_coords[1])

            avg_speed_kmh = 25
            eta_mins = int((distance_km / avg_speed_kmh) * 60)
            eta = eta_mins if eta_mins >= 1 else 1
        except Exception:
            eta = None

    return render(request, 'user/tracking.html', {
        'bus_id': bus_id,
        'bus': bus,
        'seats': seats,
        'last_row_start': last_row_start,
        'seat_grid_columns': seat_grid_columns,
        'is_bookmarked': is_bookmarked,
        'chat_room': chat_room,
        'default_pickup': default_pickup,
        'eta': eta,
        'pickup_coords': pickup_coords,
    })


@login_required
@require_POST
def bookmark_bus(request):
    try:
        bus_id = int(request.POST.get('bus_id'))
        bus = Bus.objects.get(id=bus_id)
        Bookmark.objects.get_or_create(user=request.user, bus=bus)
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'error': str(e)})


@login_required
@require_POST
def remove_bookmark(request):
    try:
        bus_id = int(request.POST.get('bus_id'))
        Bookmark.objects.filter(user=request.user, bus_id=bus_id).delete()
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'error': str(e)})


from datetime import timedelta
from django.utils import timezone


@login_required
@require_POST
def send_pickup_request(request):
    try:
        bus_id = int(request.POST.get("bus_id"))
        stop = request.POST.get("stop")
        stop_id = request.POST.get("stop_id")
        message = request.POST.get("message", "")

        bus = Bus.objects.get(id=bus_id)

        # ⭐ NEW: Check for recent duplicate requests (within 1 hour)
        one_hour_ago = timezone.now() - timedelta(hours=1)

        existing_request = PickupRequest.objects.filter(
            user=request.user,
            bus=bus,
            created_at__gte=one_hour_ago,
            status=PickupRequest.STATUS_PENDING,
        ).first()

        if existing_request:
            # User already has an active request for this bus
            time_diff = (
                timezone.now() - existing_request.created_at
            ).total_seconds() / 60
            return JsonResponse(
                {
                    "status": "error",
                    "error": f"You already have an active pickup request for this bus from {int(time_diff)} minutes ago. Please wait or cancel the previous request.",
                    "existing_request_id": existing_request.id,
                    "existing_stop": existing_request.stop,
                }
            )

        # Resolve stop_obj
        stop_obj = None
        if stop_id:
            try:
                stop_obj = Stop.objects.get(id=int(stop_id))
                stop = stop_obj.name
            except Stop.DoesNotExist:
                pass

        # Create new pickup request
        pickup = PickupRequest.objects.create(
            user=request.user, bus=bus, stop=stop, stop_obj=stop_obj, message=message
        )

        logger.info(
            "PickupRequest created: id=%s user=%s bus=%s stop=%s stop_id=%s",
            pickup.id,
            request.user.username,
            bus.id,
            stop,
            stop_obj.id if stop_obj else None,
        )

        # Send WebSocket notification to driver
        try:
            channel_layer = get_channel_layer()
            if bus.driver and bus.driver.user:
                async_to_sync(channel_layer.group_send)(
                    f"driver_{bus.driver.user.id}",
                    {
                        "type": "pickup_notification",
                        "pickup_id": pickup.id,
                        "user_id": request.user.id,
                        "user_username": request.user.username,
                        "bus_id": bus.id,
                        "stop": pickup.stop,
                        "stop_id": stop_obj.id if stop_obj else None,
                        "stop_index": pickup.get_stop_index(),
                        "message": pickup.message,
                    },
                )
        except Exception as e:
            logger.exception("Notification failed: %s", e)

        return JsonResponse(
            {
                "status": "success",
                "pickup_id": pickup.id,
                "stop_index": pickup.get_stop_index(),
                "message": "Pickup request sent successfully!",
            }
        )

    except Exception as e:
        logger.exception("send_pickup_request failed")
        return JsonResponse({"status": "error", "error": str(e)})

# ⭐ NEW: Add endpoint to cancel pickup request
@login_required
@require_POST
def cancel_pickup_request(request):
    """Allow users to cancel their own pickup requests"""
    try:
        pickup_id = int(request.POST.get('pickup_id'))
        
        pickup = PickupRequest.objects.filter(
            id=pickup_id,
            user=request.user  # Only owner can cancel
        ).first()
        
        if not pickup:
            return JsonResponse({
                'status': 'error',
                'error': 'Pickup request not found or you do not have permission'
            })
        
        # Mark as rejected instead of deleting (for history)
        pickup.status = PickupRequest.STATUS_REJECTED
        pickup.save()
        
        logger.info(
            'PickupRequest cancelled: id=%s user=%s', 
            pickup.id, request.user.username
        )
        
        return JsonResponse({
            'status': 'success',
            'message': 'Pickup request cancelled successfully'
        })
        
    except Exception as e:
        logger.exception('cancel_pickup_request failed')
        return JsonResponse({'status': 'error', 'error': str(e)})
    
@csrf_exempt
def compute_eta(request):
    """Compute ETA in minutes from the bus's current location to a pickup location.

    Accepts POST form body with 'bus_id' and 'pickup' (stop name or 'lat,lng').
    Returns JSON {status: 'success', eta: <minutes>} or error.
    """
    try:
        if request.method != 'POST':
            return JsonResponse({'status': 'error', 'error': 'POST required'})
        bus_id = int(request.POST.get('bus_id') or request.GET.get('bus_id') or 0)
        pickup = (request.POST.get('pickup') or request.GET.get('pickup') or '').strip()
        if not bus_id or not pickup:
            return JsonResponse({'status': 'error', 'error': 'bus_id and pickup required'})

        bus = Bus.objects.filter(id=bus_id).first()
        if not bus:
            return JsonResponse({'status': 'error', 'error': 'bus not found'})

        bus_lat = getattr(bus, 'current_lat', None)
        bus_lng = getattr(bus, 'current_lng', None)
        
        available_seats = bus.seats.filter(is_available=True).count()
        route = getattr(bus, 'route', None)

        if route:
            stops = route.get_stops_list()
            # find pickup stop object among route stops
            pickup_stop_obj = None
            for s in stops:
                if abs(s.latitude - float(pickup_coords[0])) < 1e-6 and abs(s.longitude - float(pickup_coords[1])) < 1e-6:
                    pickup_stop_obj = s
                    break
        

        if bus_lat is None or bus_lng is None:
            logger.warning(f"❌ Bus {bus.id} ({bus.number_plate}) has NO LIVE GPS!")
            return JsonResponse({'status': 'error', 'error': 'bus has no location data'})

        # Resolve pickup to coordinates
        pickup_coords = None
        try:
            stop_obj = Stop.objects.filter(name__iexact=pickup).first()
            if stop_obj:
                pickup_coords = (stop_obj.latitude, stop_obj.longitude)
            else:
                # try parse lat,lng
                if ',' in pickup:
                    parts = pickup.split(',')
                    pickup_coords = (float(parts[0].strip()), float(parts[1].strip()))
        except Exception:
            pickup_coords = None

        if not pickup_coords:
            return JsonResponse({'status': 'error', 'error': 'could not resolve pickup to coordinates'})

        import math
        def haversine(lat1, lon1, lat2, lon2):
            R = 6371
            phi1 = math.radians(lat1)
            phi2 = math.radians(lat2)
            dphi = math.radians(lat2 - lat1)
            dlambda = math.radians(lon2 - lon1)
            a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            return R * c

        # Prefer route-aware ETA: if the pickup matches a stop on the bus' route, compute along the stops
        distance_km = None
        try:
            route = getattr(bus, 'route', None)
            if route:
                stops = route.get_stops_list()
                # find pickup stop object among route stops
                pickup_stop_obj = None
                for s in stops:
                    if abs(s.latitude - float(pickup_coords[0])) < 1e-6 and abs(s.longitude - float(pickup_coords[1])) < 1e-6:
                        pickup_stop_obj = s
                        break
                if pickup_stop_obj and stops:
                    # helper haversine
                    def stop_distance(a, b):
                        return haversine(a.latitude, a.longitude, b.latitude, b.longitude)
                    # find nearest stop index to bus
                    nearest_idx = min(range(len(stops)), key=lambda i: haversine(bus_lat, bus_lng, stops[i].latitude, stops[i].longitude))
                    # distance from bus to the nearest stop
                    dist = haversine(bus_lat, bus_lng, stops[nearest_idx].latitude, stops[nearest_idx].longitude)
                    pickup_idx = next((i for i,s in enumerate(stops) if s.id == pickup_stop_obj.id), None)
                    if pickup_idx is not None:
                        i = nearest_idx
                        while i != pickup_idx:
                            a = stops[i]
                            b = stops[(i+1) % len(stops)]
                            dist += stop_distance(a, b)
                            i = (i+1) % len(stops)
                        distance_km = dist
        except Exception:
            distance_km = None

        if distance_km is None:
            distance_km = haversine(bus_lat, bus_lng, pickup_coords[0], pickup_coords[1])

        avg_speed_kmh = 25
        eta_mins = int((distance_km / avg_speed_kmh) * 60)
        eta_mins = eta_mins if eta_mins >= 1 else 1
        return JsonResponse({'status': 'success', 'eta': eta_mins})
    except Exception as e:
        logger.exception('compute_eta failed')
        return JsonResponse({'status': 'error', 'error': str(e)})


@login_required
def debug_bus_status(request, bus_id):
    """Return persisted debug info for a bus (staff or DEBUG only)."""
    try:
        # allow if DEBUG or staff
        if not (settings.DEBUG or (request.user.is_authenticated and request.user.is_staff)):
            return JsonResponse({'status': 'error', 'error': 'unauthorized'}, status=403)
        bus = Bus.objects.filter(id=bus_id).first()
        if not bus:
            return JsonResponse({'status': 'error', 'error': 'not found'}, status=404)
        payload = {
            'id': bus.id,
            'number_plate': getattr(bus, 'number_plate', None),
            'current_lat': getattr(bus, 'current_lat', None),
            'current_lng': getattr(bus, 'current_lng', None),
            'nearest_stop_index': getattr(bus, 'nearest_stop_index', None),
            'eta_seconds': getattr(bus, 'eta_seconds', None),
            'eta_smoothed_seconds': getattr(bus, 'eta_smoothed_seconds', None),
            'eta_passed_counter': getattr(bus, 'eta_passed_counter', None),
            'route_id': bus.route.id if getattr(bus, 'route', None) else None,
            'route_name': bus.route.name if getattr(bus, 'route', None) else None,
        }
        return JsonResponse({'status': 'success', 'bus': payload})
    except Exception as e:
        logger.exception('debug_bus_status failed')
        return JsonResponse({'status': 'error', 'error': str(e)})


@login_required
def driver_notifications(request):
    # For drivers to see pickup requests targeting their buses
    if not hasattr(request.user, 'driver_profile'):
        return JsonResponse({'status': 'error', 'error': 'Not a driver'})
    driver = request.user.driver_profile
    pickups = PickupRequest.objects.filter(bus__driver=driver).order_by('-created_at')[:50]
    unread_count = PickupRequest.objects.filter(bus__driver=driver, seen_by_driver=False).count()
    data = []
    for p in pickups:
        stop_index = p.get_stop_index()
        pickup_data = {
            'id': p.id,
            'user_id': p.user.id,
            'user': p.user.username,
            'user_username': p.user.username,
            'stop_id': p.stop_obj.id if p.stop_obj else None,
            'stop': p.stop,
            'stop_index': stop_index,
            'message': p.message,
            'status': p.status,
            'created_at': p.created_at.isoformat(),
            'seen': p.seen_by_driver,
        }
        data.append(pickup_data)
    return JsonResponse({'status': 'success', 'pickups': data, 'unread_count': unread_count, 'recent': data[:10]})


def user_profile(request, user_id):
    try:
        profile_user = User.objects.get(id=user_id)
        # pickup history for this user
        pickups = PickupRequest.objects.filter(user=profile_user).order_by('-created_at')[:200]
        # bookmarks for this user
        bookmarks = Bookmark.objects.filter(user=profile_user).select_related('bus').order_by('-created_at')[:200]

        # derive a simple "tracked_buses" list from pickups and bookmarks (unique, recent first)
        tracked = []
        seen = set()
        for p in pickups:
            if p.bus and p.bus.id not in seen:
                tracked.append(p.bus)
                seen.add(p.bus.id)
        for b in bookmarks:
            if b.bus and b.bus.id not in seen:
                tracked.append(b.bus)
                seen.add(b.bus.id)

        context = {
            'profile_user': profile_user,
            'pickups': pickups,
            'bookmarks': bookmarks,
            'tracked_buses': tracked,
        }
        return render(request, 'user/profile.html', context)
    except User.DoesNotExist:
        return render(request, 'user/profile.html', {'profile_user': None})


def logout_view(request):
    """Simple logout view that accepts GET and redirects to homepage."""
    try:
        logout(request)
    except Exception:
        pass
    return redirect('homepage')


@login_required
@require_POST
def mark_pickup_seen(request):
    try:
        pickup_id = int(request.POST.get('pickup_id'))
        p = PickupRequest.objects.filter(id=pickup_id).first()
        if not p:
            return JsonResponse({'status': 'error', 'error': 'not found'})
        # ensure driver owns the bus
        if not hasattr(request.user, 'driver_profile') or p.bus.driver != request.user.driver_profile:
            return JsonResponse({'status': 'error', 'error': 'unauthorized'})
        p.seen_by_driver = True
        p.save(update_fields=['seen_by_driver'])
        return JsonResponse({'status': 'ok'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'error': str(e)})


@login_required
@require_POST
def clear_all_pickups(request):
    try:
        if not hasattr(request.user, 'driver_profile'):
            return JsonResponse({'status': 'error', 'error': 'Not a driver'})
        driver = request.user.driver_profile
        # mark all pickups for this driver's buses as seen
        qs = PickupRequest.objects.filter(bus__driver=driver, seen_by_driver=False)
        count = qs.update(seen_by_driver=True)
        return JsonResponse({'status': 'ok', 'cleared': count})
    except Exception as e:
        return JsonResponse({'status': 'error', 'error': str(e)})


@login_required
def fetch_messages(request, other_user_id):
    # Fetch recent messages between request.user and other_user_id
    try:
        other = User.objects.get(id=other_user_id)
        msgs = Message.objects.filter(
            (models.Q(sender=request.user) & models.Q(recipient=other)) |
            (models.Q(sender=other) & models.Q(recipient=request.user))
        ).order_by('created_at')[:200]
        data = [
            {'id': m.id, 'sender': m.sender.username, 'recipient': m.recipient.username, 'content': m.content, 'created_at': m.created_at.isoformat(), 'read': m.read}
            for m in msgs
        ]
        return JsonResponse({'status': 'success', 'messages': data})
    except Exception as e:
        return JsonResponse({'status': 'error', 'error': str(e)})

@login_required
@require_POST
def switch_route(request):
    """
    Switch driver's bus to the reverse route.
    """
    try:
        # Verify user is a driver
        if not hasattr(request.user, 'driver_profile'):
            return JsonResponse({
                'status': 'error', 
                'error': 'Not authorized. User is not a driver.'
            }, status=403)
        
        driver = request.user.driver_profile
        bus = driver.buses.first()
        
        if not bus:
            return JsonResponse({
                'status': 'error',
                'error': 'No bus found for this driver.'
            }, status=404)
        
        current_route = bus.route
        
        if not current_route:
            return JsonResponse({
                'status': 'error',
                'error': 'Bus has no current route assigned.'
            }, status=400)
        
        # Get the reverse route
        reverse_route = current_route.reverse_route
        
        if not reverse_route:
            return JsonResponse({
                'status': 'error',
                'error': f'No reverse route configured for {current_route.name}. Please contact admin.'
            }, status=400)
        
        # Perform the switch
        old_route_name = current_route.name
        new_route_name = reverse_route.name
        
        bus.route = reverse_route
        
        # Reset location tracking state when switching routes
        bus.nearest_stop_index = None
        bus.eta_seconds = None
        bus.eta_smoothed_seconds = None
        bus.eta_passed_counter = 0
        
        bus.save(update_fields=[
            'route', 
            'nearest_stop_index', 
            'eta_seconds', 
            'eta_smoothed_seconds',
            'eta_passed_counter'
        ])
        
        logger.info(
            f'Driver {driver.user.username} (Bus {bus.number_plate}) '
            f'switched route: {old_route_name} → {new_route_name}'
        )
        
        return JsonResponse({
            'status': 'success',
            'message': f'Route switched successfully!',
            'old_route': old_route_name,
            'new_route': new_route_name,
            'route_id': reverse_route.id,
            'route_name': reverse_route.name
        })
        
    except Exception as e:
        logger.exception(f'Route switch failed: {e}')
        return JsonResponse({
            'status': 'error',
            'error': f'Failed to switch route: {str(e)}'
        }, status=500)


@login_required
def get_route_info(request):
    """
    Get current route information including reverse route availability.
    """
    try:
        if not hasattr(request.user, 'driver_profile'):
            return JsonResponse({
                'status': 'error',
                'error': 'Not authorized'
            }, status=403)
        
        driver = request.user.driver_profile
        bus = driver.buses.first()
        
        if not bus or not bus.route:
            return JsonResponse({
                'status': 'error',
                'error': 'No route assigned'
            }, status=404)
        
        current_route = bus.route
        reverse_route = current_route.reverse_route
        
        return JsonResponse({
            'status': 'success',
            'current_route': {
                'id': current_route.id,
                'name': current_route.name,
                'stops_count': len(current_route.get_stops_list())
            },
            'reverse_route': {
                'id': reverse_route.id,
                'name': reverse_route.name,
                'stops_count': len(reverse_route.get_stops_list())
            } if reverse_route else None,
            'can_switch': bool(reverse_route)
        })
        
    except Exception as e:
        logger.exception(f'Get route info failed: {e}')
        return JsonResponse({
            'status': 'error',
            'error': str(e)
        }, status=500)
