"""
API views for representative lookup.
"""

import json
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from .services import RepLookupService


@csrf_exempt  # For development - in production, use proper CSRF handling
@require_http_methods(["POST"])
def lookup_reps(request):
    """
    API endpoint to look up representatives by address.

    POST /api/reps/lookup/
    Body: {"address": "123 Main St, Seattle, WA"}

    Returns:
        200 OK:
            {
                "success": true,
                "data": {
                    "district": {
                        "number": "7",
                        "name": "District 7"
                    },
                    "representatives": [...]
                }
            }

        404 Not Found:
            {
                "success": false,
                "error": "Address not found or not in Seattle"
            }

        400 Bad Request:
            {
                "success": false,
                "error": "Address parameter is required"
            }
    """
    try:
        # Parse JSON body
        data = json.loads(request.body)
        address = data.get('address', '').strip()

        if not address:
            return JsonResponse({
                'success': False,
                'error': 'Address parameter is required'
            }, status=400)

        # Look up the district and representatives
        service = RepLookupService()
        result = service.lookup_by_address(address)

        if not result:
            return JsonResponse({
                'success': False,
                'error': 'Address not found or not in Seattle'
            }, status=404)

        return JsonResponse({
            'success': True,
            'data': result
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON in request body'
        }, status=400)

    except Exception as e:
        # Log the error in production
        print(f"Error in lookup_reps: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Internal server error'
        }, status=500)
