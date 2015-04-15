'''
HTTP Verb   Path    View method Used for
POST    /analyses   analysis.views.analysis.create  Create a new analysis
GET /analyses   analysis.views.analysis.index   Show all analyses. Accepts param ?status=ready
PUT /analyses/$id   analysis.views.analysis.update  Update analysis. (used to set status=done)
'''

from django.http import JsonResponse
from django.shortcuts import render
from django.core import serializers
from django.views.decorators.csrf import csrf_exempt
from .helpers.runrequest import RunRequestHelper
from .helpers.runrequest import RunRequestValidationError
#from apps.analysis.models import AnalysisRequest

from apps.analysis.models import AnalysisStatus
from apps.analysis.models import Analysis
from apps.analysis.models import Pipeline
from apps.analysis.models import Session

import traceback

import json
import uuid
import sys

# update the status of a analysis
@csrf_exempt
def update(request):
    query = json.loads(request.body)
    if 'analysis_id' in query:
        status = AnalysisStatus.objects.get(analysis = Analysis(analysisid=query['analysis_id']))
        status.updateStatus(query)
        objs = [ AnalysisStatus.objects.get(analysis = Analysis(analysisid=query['analysis_id'])) ]
        return JsonResponse(serializers.serialize('json', objs), safe=False, status=200)
    else:
        return JsonResponse({'msg':'wrong analysis ID'}, status=200)

# indexing the analysis
@csrf_exempt
def index(request):
    try:
        query = json.loads('{}')
        if len(request.body)>0:
            query = json.loads(request.body)
    except:
        e = sys.exc_info()[0]
        return JsonResponse({"msg":"input json format error"+str(e), "input":request.body}, safe=False, status=200)

    if 'analysis_id' in query:
        try:
            analysis = Analysis.objects.get(analysisid=query['analysis_id'])
            return JsonResponse(analysis.prepareJSON(), safe=False, status=200)
        except:
            return JsonResponse({"msg":"can't find the analysis:"+str(query['analysis_id'])}, safe=False, status=200)
    else:
        # return the todo list
        return JsonResponse( serializers.serialize('json',AnalysisStatus.objects.filter(status=0).all()), safe=False, status=200)

@csrf_exempt
def create(request):
    try:
        data = json.loads(request.body)
    except ValueError as err:
        return JsonResponse({"message": 'Error: Input is not in valid JSON format: "%s" ' % err}, status=400)

    # TODO wait the schema validation function to be done
    try:
        clean_data_json = RunRequestHelper.clean_json(request.body)
    except RunRequestValidationError as e:
        return JsonResponse({"message": 'Error validating the run request. "%s"' % (e.message+"<br>"+str(traceback.format_exc()))}, status=400)
    

    # AnalysisRequest.create(clean_data_json)
    # TODO a test run request
    # parsing the json input
    query = json.loads(request.body)
    pipeline = Pipeline(pipelineid="test", pipelinename="tst_pipeline", comment="")
    msg = pipeline.jsonToClass( query )
    pipeline.save()

    # send the pipeline into queue system
    analysis = Analysis(analysisid=str(uuid.uuid1()), pipelineid=pipeline, comment="autogenerated", ownerid=0)
    analysis.save()
    status = AnalysisStatus(statusid=str(uuid.uuid1()), analysis=analysis, status=0)
    status.save()
    msg = "start analysis: "+analysis.analysisid
    return JsonResponse({'analysis_id':analysis.analysisid,'comment':msg}, status=200)
 

# analysis web query: entry
@csrf_exempt
def analyses(request):
    if request.method == 'GET':
        #return JsonResponse({'msg':'GET'}, status=200)
        return index(request)
    elif request.method == 'POST':
        #return JsonResponse({'msg':'POST'}, status=200)
        return create(request)


