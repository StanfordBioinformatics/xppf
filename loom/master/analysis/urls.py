from django.conf.urls import patterns, include, url
from analysis.models import *

urlpatterns = patterns(
    '',
    url(r'^status/$', 'analysis.views.status'),
    url(r'^workerinfo/$', 'analysis.views.workerinfo'),
    url(r'^filehandlerinfo/$', 'analysis.views.filehandlerinfo'),
    url(r'^servertime/$', 'analysis.views.servertime'),
    url(r'^controls/update/$', 'analysis.views.update_tasks'),
    url(r'^controls/run/$', 'analysis.views.run_tasks'),
)    

model_classes = [
    DataObject,
    DataObjectArray,
    DataSourceRecord,
    FileDataObject,
    FileStorageLocation,
    Workflow,
    WorkflowRun,
    Step,
    StepRun,
    TaskRun,
    TaskRunLog,
]

for cls in model_classes:
    urlpatterns.append(url(r'^%s/$' % cls.get_class_name(plural=True), 'analysis.views.create_or_index', {'model_class': cls}))
    urlpatterns.append(url(r'^%s/(?P<id>[a-zA-Z0-9_\-]+)/$' % cls.get_class_name(plural=True), 'analysis.views.show_or_update', {'model_class': cls}))

urlpatterns.append(url(r'^%s/(?P<id>[a-zA-Z0-9_\-]+)/file_storage_locations/$' % FileDataObject.get_class_name(plural=True), 'analysis.views.storage_locations_by_file'))
urlpatterns.append(url(r'^%s/(?P<id>[a-zA-Z0-9_\-]+)/data_source_records/$' % FileDataObject.get_class_name(plural=True), 'analysis.views.data_source_records_by_file'))

