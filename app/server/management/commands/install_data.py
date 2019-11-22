from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError
from django.conf import settings
from api.models import Project

class Command(BaseCommand):
  help = 'Non-interactively install data from file of ids'

  def handle(self, *args, **options):
    projectname = options.get('projectname')
    if not projectname:
      raise CommandError('--rolename  --projectname  --username are required for the rolemapping')

    if projectname:
      try:
        project = Project.objects.create(name=projectname)
        project.id
      except KeyError as key_error:
        self.stderr.write(self.style.ERROR(f'Missing Key: "{key_error}"'))
      for role_name in role_names:
        role = Role()
        role.name = role_name
        try:
          role.save()
        except DatabaseError as db_error:
          self.stderr.write(self.style.ERROR(f'Datbase Error: "{db_error}"'))
        else:
          self.stdout.write(self.style.SUCCESS(f'Role created successfully "{role_name}"'))
