
from django.contrib import admin
from .models import Driver, BusRoute, Bus, EmailOTP, Seat, VehicleDocument, Stop, RouteStop,EmailOTP

# Inline for RouteStop in BusRoute
class RouteStopInline(admin.TabularInline):
	model = RouteStop
	extra = 1
	autocomplete_fields = ['stop']
	ordering = ('order',)

# Inline for Seat
class SeatInline(admin.TabularInline):
	model = Seat
	extra = 0
	show_change_link = False

# Inline for Bus
class BusInline(admin.StackedInline):
	model = Bus
	extra = 0
	show_change_link = True
	readonly_fields = ('route',)

# Inline for VehicleDocument
class VehicleDocumentInline(admin.TabularInline):
	model = VehicleDocument
	extra = 0
	show_change_link = False



@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
	readonly_fields = ('user', 'phone', 'vehicle_number', 'current_lat', 'current_lng')
	list_display = ('user', 'phone', 'vehicle_number', 'verified', 'get_route')
	list_filter = ('verified',)
	search_fields = ('user__username', 'phone', 'vehicle_number')
	fields = ('user', 'phone', 'vehicle_number', 'verified', 'current_lat', 'current_lng')
	inlines = [BusInline, VehicleDocumentInline]

	def get_route(self, obj):
		bus = obj.buses.first()
		if bus and bus.route:
			return bus.route.name
		return '(No route)'
	get_route.short_description = 'Route'

@admin.register(BusRoute)
class BusRouteAdmin(admin.ModelAdmin):
	list_display = ('name', 'is_active')
	search_fields = ('name',)
	inlines = [RouteStopInline]
 
@admin.register(EmailOTP)
class EmailOTPAdmin(admin.ModelAdmin):
    list_display = ('email', 'otp_code', 'created_at', 'is_verified')
    list_filter = ('is_verified', 'created_at')
    search_fields = ('email',)
    readonly_fields = ('created_at',)

@admin.register(Stop)
class StopAdmin(admin.ModelAdmin):
	list_display = ('name', 'latitude', 'longitude')
	search_fields = ('name',)

