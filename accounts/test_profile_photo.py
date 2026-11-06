import json
import tempfile
from io import BytesIO
from PIL import Image
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from accounts.models import Official


class ProfilePhotoTests(TransactionTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = override_settings(MEDIA_ROOT=directory.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.user = User.objects.create_user('photo', password='Test-profile-123')
        self.official = Official.objects.create(user=self.user, full_name='Perfil Foto',
            national_id='photo-test', email='photo@example.test')
        self.client.force_login(self.user)

    def photo(self, fmt='PNG'):
        image = Image.new('RGB', (100, 80), 'red')
        image.paste('blue', (50, 0, 100, 80))
        output = BytesIO()
        image.save(output, fmt)
        return SimpleUploadedFile('image.' + fmt.lower(), output.getvalue(), content_type='image/' + fmt.lower())

    def payload(self):
        return dict(email=self.official.email, phone='', photo=self.photo(),
            photo_crop=json.dumps(dict(x=50, y=0, width=50, height=50)))

    def test_crop_persists_actual_pixels_and_only_own_profile(self):
        other = Official.objects.create(full_name='Otro', national_id='other-photo', email='other@example.test')
        data = self.payload()
        data.update(official=other.pk, user=999, is_superuser=True)
        self.assertEqual(self.client.post(reverse('my_profile'), data).status_code, 302)
        self.official.refresh_from_db()
        other.refresh_from_db()
        self.assertFalse(other.photo)
        with self.official.photo.open('rb') as stream:
            image = Image.open(stream)
            self.assertEqual(image.size, (50, 50))
            red, green, blue = image.getpixel((25, 25))
            self.assertGreater(blue, 200)
            self.assertLess(red, 20)
        self.assertContains(self.client.get(reverse('my_profile')), reverse('my_profile_photo'))
        response = self.client.get(reverse('my_profile_photo'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        response.close()
        other_user = User.objects.create_user('other-photo')
        other.user = other_user
        other.save()
        self.client.force_login(other_user)
        self.assertEqual(self.client.get(reverse('my_profile_photo'), {'official': self.official.pk}).status_code, 404)

    def test_invalid_uploads_and_crop_do_not_write(self):
        cases = [SimpleUploadedFile('fake.png', b'not an image', content_type='image/png'),
                 self.photo('GIF'), SimpleUploadedFile('big.png', self.photo().read() + b'x' * (2 * 1024 * 1024), content_type='image/png')]
        for uploaded in cases:
            data = self.payload()
            data.update(photo=uploaded, email='changed@example.test')
            response = self.client.post(reverse('my_profile'), data)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors.get('photo'))
            self.official.refresh_from_db()
            self.assertFalse(self.official.photo)
            self.assertEqual(self.official.email, 'photo@example.test')
        for crop in ['', '{}', 'null', json.dumps(dict(x=-1,y=0,width=50,height=50)),
                     json.dumps(dict(x=0,y=0,width=80,height=40)),
                     json.dumps(dict(x=50,y=0,width=500,height=50))]:
            data = self.payload()
            data['photo_crop'] = crop
            self.assertTrue(self.client.post(reverse('my_profile'), data).context['form'].errors.get('photo'))

    def test_contact_only_update_preserves_existing_photo(self):
        self.client.post(reverse('my_profile'), self.payload())
        self.official.refresh_from_db()
        name = self.official.photo.name
        self.client.post(reverse('my_profile'), {'email':self.official.email, 'phone':'222222222'})
        self.official.refresh_from_db()
        self.assertEqual(self.official.photo.name, name)

    def test_transparent_and_semitransparent_pixels_are_composited_on_white(self):
        image = Image.new('RGBA', (100, 80), (0, 0, 0, 0))
        image.paste((255, 0, 0, 128), (0, 40, 100, 80))
        output = BytesIO()
        image.save(output, 'PNG')
        data = self.payload()
        data['photo'] = SimpleUploadedFile('transparent.png', output.getvalue(), content_type='image/png')
        data['photo_crop'] = json.dumps(dict(x=0, y=0, width=80, height=80))
        self.assertEqual(self.client.post(reverse('my_profile'), data).status_code, 302)
        self.official.refresh_from_db()
        with self.official.photo.open('rb') as stream:
            saved = Image.open(stream)
            self.assertEqual(saved.mode, 'RGB')
            self.assertTrue(all(value > 245 for value in saved.getpixel((20, 20))))
            red, green, blue = saved.getpixel((20, 60))
            self.assertGreater(red, 245)
            self.assertTrue(115 < green < 140)
            self.assertTrue(115 < blue < 140)

    def test_photo_requires_own_authenticated_session(self):
        self.assertEqual(self.client.get(reverse('my_profile_photo')).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('my_profile_photo')).status_code, 302)
        self.assertEqual(self.client.get(reverse('my_profile')).status_code, 302)
