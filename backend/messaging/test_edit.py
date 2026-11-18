from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from .models import MessageTemplate, Option, Question


class EditDeleteTests(APITestCase):
    def setUp(self):
        self.client.force_authenticate(user=User.objects.create_user('t', 't@example.com', 'pw'))
        self.tpl = MessageTemplate.objects.create(name='Survey', description='old')
        self.q = Question.objects.create(template=self.tpl, text='Ready?')
        self.yes = Option.objects.create(question=self.q, title='yes')
        self.no = Option.objects.create(question=self.q, title='no')
        self.child = Question.objects.create(template=self.tpl, text='Why?', parent_option=self.yes)

    # ---- templates ----
    def test_view_edit_template(self):
        url = f'/api/templates/{self.tpl.id}/'
        self.assertEqual(self.client.get(url).json()['name'], 'Survey')
        r = self.client.patch(url, {'name': ' New name ', 'description': 'new'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.tpl.refresh_from_db()
        self.assertEqual((self.tpl.name, self.tpl.description), ('New name', 'new'))

    def test_edit_template_validation(self):
        url = f'/api/templates/{self.tpl.id}/'
        self.assertEqual(self.client.patch(url, {'name': '   '}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(url, {'description': ''}, format='json').status_code, 400)

    def test_delete_template_removes_its_flow(self):
        admin = User.objects.create_superuser('boss', 'boss@example.com', 'admin-pass-1')
        self.client.force_authenticate(user=admin)
        r = self.client.delete(f'/api/templates/{self.tpl.id}/', {'password': 'admin-pass-1'}, format='json')
        self.assertEqual(r.status_code, 204)
        self.assertEqual((MessageTemplate.objects.count(), Question.objects.count(), Option.objects.count()), (0, 0, 0))

    def test_template_endpoints_need_login(self):
        self.client.force_authenticate(user=None)
        url = f'/api/templates/{self.tpl.id}/'
        for call in (self.client.get, self.client.patch, self.client.delete):
            self.assertEqual(call(url).status_code, 401)

    # ---- questions ----
    def test_edit_question_text(self):
        r = self.client.patch(f'/api/questions/{self.q.id}/', {'text': ' Are you sure? '}, format='json')
        self.assertEqual(r.status_code, 200)
        self.q.refresh_from_db()
        self.assertEqual(self.q.text, 'Are you sure?')
        self.assertEqual(self.client.patch(f'/api/questions/{self.q.id}/', {'text': ''}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(f'/api/questions/{self.q.id}/', {'text': 'x' * 1025}, format='json').status_code, 400)

    # ---- options ----
    def test_edit_option_title(self):
        r = self.client.patch(f'/api/options/{self.yes.id}/', {'title': 'absolutely'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.yes.refresh_from_db()
        self.assertEqual(self.yes.title, 'absolutely')
        # its follow-up question stays attached
        self.child.refresh_from_db()
        self.assertEqual(self.child.parent_option_id, self.yes.id)

    def test_edit_option_keeps_own_title_but_rejects_clash_and_bad_values(self):
        url = f'/api/options/{self.yes.id}/'
        self.assertEqual(self.client.patch(url, {'title': 'YES'}, format='json').status_code, 200)  # same option
        self.assertEqual(self.client.patch(url, {'title': 'no'}, format='json').status_code, 400)  # clashes with sibling
        self.assertEqual(self.client.patch(url, {'title': ''}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(url, {'title': 'x' * 21}, format='json').status_code, 400)

    def test_still_cannot_exceed_three_options(self):
        Option.objects.create(question=self.q, title='maybe')
        r = self.client.post(f'/api/questions/{self.q.id}/options/', {'title': 'four'}, format='json')
        self.assertEqual(r.status_code, 400)
