from io import BytesIO
import time
from authy.api import AuthyApiClient
from flask import current_app, request
from flask_login import current_user
import jwt
import qrcode
import qrcode.image.svg


def get_registration_jwt(user_id, expires_in=5 * 60):
    """Return a JWT for Authy registration.

    :param user_id: the ID of the user.
    :param expires_in: the validaty time for the token in seconds.

    :returns a JWT token that can be used to register the user with Authy.
    """
    now = time.time()
    payload = {
        'iss': current_app.config['AUTHY_APP_NAME'],
        'iat': now,
        'exp': now + expires_in,
        'context': {
            'custom_user_id': str(user_id),
            'authy_app_id': current_app.config['AUTHY_APP_ID'],
        },
    }
    return jwt.encode(payload,
                      current_app.config['AUTHY_PRODUCTION_API_KEY']).decode()


def get_qrcode(jwt):
    """Return an Authy registration QR code for the given JWT.

    :param jwt: Authy registration JWT.

    :returns a bytes object with the QR code image in SVG format.
    """
    qr = qrcode.make('authy://account?token=' + jwt,
                     image_factory=qrcode.image.svg.SvgImage)
    stream = BytesIO()
    qr.save(stream)
    return stream.getvalue()


def get_registration_status(user_id):
    """Check if the given user has scanned the QR code to register.

    :param user_id: the ID of the user.

    :returns a dict with 'status' and 'authy_id' keys. The status is
             'completed' if the user already scanned the QR code, or 'pending'
             if they didn't yet. Any other status should be considered an
             error. If the status is 'completed' then the 'authy_id' key
             contains the ID assigned by Authy to this user.
    """
    authy_api = AuthyApiClient(current_app.config['AUTHY_PRODUCTION_API_KEY'])
    resp = authy_api.users.registration_status(user_id)
    if not resp.ok():
        return {'status': 'pending'}
    return resp.content['registration']


def delete_user(authy_id):
    """Unregister a user from Authy push notifications.

    :param authy_id: the Authy ID for the user.

    :returns True if successful or False otherwise.
    """
    authy_api = AuthyApiClient(current_app.config['AUTHY_PRODUCTION_API_KEY'])
    resp = authy_api.users.delete(authy_id)
    return resp.ok()


def send_push_authentication(user):
    """Send a push authentication notification to a user.

    :param authy_id: the Authy ID for the user

    :returns a unique ID for the push notification or None if there was an
             error.
    """
    authy_api = AuthyApiClient(current_app.config['AUTHY_PRODUCTION_API_KEY'])
    resp = authy_api.one_touch.send_request(
        user.authy_id,
        "Login requested for Microblog.",
        details={
            'Username': user.username,
            'IP Address': request.remote_addr,
        },
        seconds_to_expire=120)
    if not resp.ok():
        return None
    return resp.get_uuid()


def check_push_authentication_status(uuid):
    """Check if a push notification has been handled.

    :param uuid: the ID of the push notification.

    :returns 'approved', 'pending' or 'error'
    """
    authy_api = AuthyApiClient(current_app.config['AUTHY_PRODUCTION_API_KEY'])
    resp = authy_api.one_touch.get_approval_status(uuid)
    if not resp.ok():
        return 'error'
    return resp.content['approval_request']['status']
