import re

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase

from .models import AuditLog

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
NEW_PASSWORD = 'Brand-new-pass-77'


@override_settings(OTP_EMAIL_ASYNC=False)
class ProfileTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_superuser('boss@example.com', 'boss@example.com', 'old-pass-12345')
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

    def test_requires_login(self):
        anon = APIClient()
        for url in ('/api/profile/', '/api/profile/avatar/'):
            self.assertEqual(anon.get(url).status_code, 401, url)
        self.assertEqual(anon.post('/api/profile/password/send-otp/').status_code, 401)

    def test_get_and_update_name_and_phone(self):
        self.assertEqual(self.client.get('/api/profile/').json()['email'], 'boss@example.com')
        r = self.client.patch('/api/profile/', {'name': '  Asha   Rao ', 'phone_number': '9876543210'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        p = r.json()['profile']
        self.assertEqual((p['name'], p['phone_number']), ('Asha Rao', '919876543210'))  # country code added
        log = AuditLog.objects.get(entity_type='profile')
        self.assertEqual(log.changes['name'], {'from': '', 'to': 'Asha Rao'})

    def test_rejects_bad_name_or_phone(self):
        self.assertEqual(self.client.patch('/api/profile/', {'name': 'x' * 101}, format='json').status_code, 400)
        self.assertEqual(self.client.patch('/api/profile/', {'phone_number': 'abc'}, format='json').status_code, 400)
        self.assertEqual(self.client.patch('/api/profile/', {'phone_number': ''}, format='json').status_code, 200)

    def test_avatar_upload_view_remove_and_validation(self):
        up = lambda data, name='a.png': self.client.post(  # noqa: E731
            '/api/profile/avatar/', {'image': SimpleUploadedFile(name, data)}, format='multipart')
        self.assertEqual(self.client.get('/api/profile/avatar/').status_code, 404)
        self.assertEqual(up(b'GIF89a not allowed').status_code, 400)  # judged by content
        self.assertEqual(up(PNG + b'x' * (2 * 1024 * 1024)).status_code, 400)  # too big
        r = up(PNG)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['profile']['has_avatar'])
        got = self.client.get('/api/profile/avatar/')
        self.assertEqual((got.status_code, got['Content-Type'], got.content), (200, 'image/png', PNG))
        self.assertEqual(self.client.delete('/api/profile/avatar/').status_code, 200)
        self.assertEqual(self.client.get('/api/profile/avatar/').status_code, 404)

    def test_change_password_by_email_code_rotates_the_login_token(self):
        other = Token.objects.create(user=User.objects.create_user('x', 'x@example.com', 'p'))
        self.assertEqual(self.client.post('/api/profile/password/send-otp/').status_code, 200)
        self.assertEqual(mail.outbox[0].to, ['boss@example.com'])
        code = re.search(r'code is (\d{6})', mail.outbox[0].body).group(1)
        wrong = '000000' if code != '000000' else '111111'
        self.assertEqual(self.client.post('/api/profile/password/verify-otp/', {'otp': wrong}, format='json').status_code, 400)
        token = self.client.post('/api/profile/password/verify-otp/', {'otp': code}, format='json').json()['reset_token']
        body = {'reset_token': token, 'password': NEW_PASSWORD, 'confirm_password': 'different'}
        self.assertEqual(self.client.post('/api/profile/password/change/', body, format='json').status_code, 400)
        body['confirm_password'] = NEW_PASSWORD
        done = self.client.post('/api/profile/password/change/', body, format='json')
        self.assertEqual(done.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        new_key = done.json()['token']
        self.assertNotEqual(new_key, self.token.key)
        self.assertFalse(Token.objects.filter(key=self.token.key).exists())  # old login (any device) is dead
        self.assertTrue(Token.objects.filter(user=self.user, key=new_key).exists())  # this session continues
        self.assertTrue(Token.objects.filter(key=other.key).exists())  # other users untouched
        self.assertNotIn(NEW_PASSWORD + code + token, str(list(AuditLog.objects.values())))

    def test_cannot_change_password_without_the_code(self):
        r = self.client.post('/api/profile/password/change/',
                             {'reset_token': 'nope', 'password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD}, format='json')
        self.assertEqual(r.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('old-pass-12345'))
