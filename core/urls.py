from django.urls import path
from . import views

urlpatterns = [
    path("", views.homepage, name="homepage"),
    path("driver/register/", views.driver_register, name="driver_register"),
    path("driver/login/", views.driver_login, name="driver_login"),
    path("driver/dashboard/", views.driver_dashboard, name="driver_dashboard"),
    path("api/update_location/", views.update_location, name="update_location"),
    path("user/login/", views.user_login, name="user_login"),
    path("user/register/", views.user_register, name="user_register"),
    path("track/<int:bus_id>/", views.track_bus, name="track_bus"),
    path("api/toggle_seat/", views.toggle_seat, name="toggle_seat"),
    path("api/bookmark_bus/", views.bookmark_bus, name="bookmark_bus"),
    path("api/remove_bookmark/", views.remove_bookmark, name="remove_bookmark"),
    path("api/send_pickup/", views.send_pickup_request, name="send_pickup"),
    path(
        "driver/notifications/", views.driver_notifications, name="driver_notifications"
    ),
    path("api/mark_pickup_seen/", views.mark_pickup_seen, name="mark_pickup_seen"),
    path("api/clear_all_pickups/", views.clear_all_pickups, name="clear_all_pickups"),
    path("user/profile/<int:user_id>/", views.user_profile, name="user_profile"),
    path("messages/<int:other_user_id>/", views.fetch_messages, name="fetch_messages"),
    path("api/clear_chat/<int:other_user_id>/", views.clear_chat, name="clear_chat"),
    path("api/compute_eta/", views.compute_eta, name="compute_eta"),
    path(
        "debug/bus_status/<int:bus_id>/",
        views.debug_bus_status,
        name="debug_bus_status",
    ),
    # custom logout view (accepts GET) for convenience
    path("logout/", views.logout_view, name="logout"),
    # Forgot Password URLs
    path(
        "driver/forgot-password/",
        views.driver_forgot_password,
        name="driver_forgot_password",
    ),
    path(
        "driver/verify-reset-otp/",
        views.driver_verify_reset_otp,
        name="driver_verify_reset_otp",
    ),
    path(
        "driver/set-new-password/",
        views.driver_set_new_password,
        name="driver_set_new_password",
    ),
    # User Forgot Password URLs
    path(
        "user/forgot-password/", views.user_forgot_password, name="user_forgot_password"
    ),
    path(
        "user/verify-reset-otp/",
        views.user_verify_reset_otp,
        name="user_verify_reset_otp",
    ),
    path(
        "user/set-new-password/",
        views.user_set_new_password,
        name="user_set_new_password",
    ),
    path("api/switch_route/", views.switch_route, name="switch_route"),
    path("api/route_info/", views.get_route_info, name="get_route_info"),
    path("api/cancel_pickup/", views.cancel_pickup_request, name="cancel_pickup"),
    path("api/reserve_seat/", views.reserve_seat_for_pickup, name="reserve_seat"),
    path(
        "api/cancel_pickup_request/",
        views.cancel_pickup_request,
        name="cancel_pickup_request",
    ),
    path(
        "api/cancel_seat_reservation/",
        views.cancel_seat_reservation,
        name="cancel_seat_reservation",
    ),
]
