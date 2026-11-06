import uuid

from django.db import models


class DemoAnswer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    earned_points = models.FloatField()
