# Generated by Django 3.0.4 on 2020-06-07 20:01

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0011_camera_name'),
    ]

    operations = [
        migrations.AlterField(
            model_name='camera',
            name='name',
            field=models.CharField(max_length=50, validators=[django.core.validators.RegexValidator(message='Enter a valid name: use english letters, numbers and underscores', regex='^[a-zA-Z0-9-_]+$')]),
        ),
    ]
