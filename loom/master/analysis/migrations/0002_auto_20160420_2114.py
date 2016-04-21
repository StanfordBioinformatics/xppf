# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
import sortedone2many.fields
import universalmodels.models
import django.utils.timezone
import analysis.models.base


class Migration(migrations.Migration):

    dependencies = [
        ('analysis', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='TaskRunLog',
            fields=[
                ('_id', models.UUIDField(default=universalmodels.models.uuid_str, serialize=False, editable=False, primary_key=True)),
                ('datetime_created', models.DateTimeField(default=django.utils.timezone.now)),
                ('datetime_updated', models.DateTimeField(default=django.utils.timezone.now)),
                ('logname', models.CharField(max_length=255)),
                ('logfile', models.ForeignKey(to='analysis.FileDataObject')),
            ],
            options={
                'abstract': False,
            },
            bases=(models.Model, analysis.models.base._ModelMixin),
        ),
        migrations.RemoveField(
            model_name='workflowrunoutput',
            name='data_object',
        ),
        migrations.AddField(
            model_name='steprun',
            name='workflow_name',
            field=models.CharField(default=b'', max_length=255),
        ),
        migrations.AddField(
            model_name='steprun',
            name='workflow_run_datetime_created',
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name='taskrun',
            name='step_name',
            field=models.CharField(default=b'', max_length=255),
        ),
        migrations.AddField(
            model_name='taskrun',
            name='workflow_name',
            field=models.CharField(default=b'', max_length=255),
        ),
        migrations.AddField(
            model_name='taskrun',
            name='workflow_run_datetime_created',
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name='taskrun',
            name='logs',
            field=sortedone2many.fields.SortedOneToManyField(help_text=None, related_name='task_run', to='analysis.TaskRunLog'),
        ),
    ]
