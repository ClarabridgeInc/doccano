import os

from django.conf import settings
from django.test import override_settings
from rest_framework import status
from rest_framework.reverse import reverse
from rest_framework.test import APITestCase
from model_mommy import mommy

from ...api.models import User, SequenceAnnotation, Document, Role, RoleMapping
from ...api.models import SEQUENCE_LABELING
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')


class TestUploader(APITestCase):

  @classmethod
  def setUpTestData(cls):
    super_user = User.objects.get_by_natural_key(username="admin")
    cls.labeling_project = mommy.make('SequenceLabelingProject',
                                      users=[super_user], project_type=SEQUENCE_LABELING)

  def file_server_upload_test_helper(self, project_id, member, filename, expected_status, **kwargs):
    query_params = {
      'project_id': project_id,
      'member': member,
      'file_name': filename,
    }

    query_params.update(kwargs)

    response = self.client.get(reverse('file_server_uploader'), query_params)

    self.assertEqual(response.status_code, expected_status)

  def test_cannot_upload_with_missing_file(self):
    self.file_server_upload_test_helper(project_id=self.labeling_project.id,
                                        member=settings.MEMBER,
                                        filename='does-not-exist',
                                        expected_status=status.HTTP_400_BAD_REQUEST)