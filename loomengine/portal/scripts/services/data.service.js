'use strict';

angular
    .module('loom.services')
    .service('DataService', DataService)

DataService.$inject = ['$http', '$q'];

function DataService($http, $q) {
    /* DataService retrieves and caches data from the server. */
    
    this.setActiveRun = setActiveRun;
    this.setActiveTemplate = setActiveTemplate;
    this.setActiveFile = setActiveFile;
    this.getAllActive = getAllActive;
    this.getRuns = getRuns;
    this.getTemplates = getTemplates;
    this.getImportedFiles = getImportedFiles;
    this.getResultFiles = getResultFiles;
    this.getLogFiles = getLogFiles;
    this.getFileProvenance = getFileProvenance;

    var activeData = {};
    
    function getAllActive() {
	return activeData;
    };

    function setActiveRun(runId) {
	return $http.get('/api/runs/' + runId + '/')
            .then(function(response) {
		activeData.run = response.data;
		expandRunInputsOutputs();
	    });
    };

    function expandRunInputsOutputs() {
	for (var i=0; i < activeData.run.inputs.length; i++) {
	    expandRunInput(i);
	}
	for (var i=0; i < activeData.run.outputs.length; i++) {
	    expandRunOutput(i);
	}
    };

    function expandRunInput(i) {
	return $http.get('/api/data-trees/'+activeData.run.inputs[i].data.uuid)
	    .then(function(response) {
		activeData.run.inputs[i].data = response.data;
	    });
    };

    function expandRunOutput(i) {
	return $http.get('/api/data-trees/'+activeData.run.outputs[i].data.uuid)
	    .then(function(response) {
		activeData.run.outputs[i].data = response.data;
	    });
    };

    function setActiveTemplate(templateId) {
	return $http.get('/api/templates/' + templateId + '/')
            .then(function(response) {
		activeData.template = response.data;
		expandTemplateInputs();
            });
    };

    function expandTemplateInputs() {
	for (var i=0; i < activeData.template.fixed_inputs.length; i++) {
	    expandTemplateFixedInput(i);
	}
    };

    function expandTemplateFixedInput(i) {
	return $http.get('/api/data-trees/'+activeData.template.fixed_inputs[i].data.uuid)
	    .then(function(response) {
		activeData.template.fixed_inputs[i].data = response.data;
	    });
    };

    function setActiveFile(fileId) {
	return $http.get('/api/data-files/' + fileId + '/')
            .then(function(response) {
		activeData.file = response.data;
            });
    };

    function getFileProvenance(fileId) {
	return $http.get('/api/data-files/' + fileId + '/provenance/')
	    .then(function(response) {
		return response.data.provenance;
	    });
    };

    function getRuns() {
	return $http.get('/api/runs/?parent_only')
	    .then(function(response) {
		return response.data;
	    });
    };

    function getTemplates() {
	return $http.get('/api/templates/?imported')
	    .then(function(response) {
		return response.data;
	    });
    };

    function getImportedFiles() {
	return $http.get('/api/data-files/?source_type=imported')
	    .then(function(response) {
		return response.data;
	    });
    };
    function getResultFiles() {
	return $http.get('/api/data-files/?source_type=result')
	    .then(function(response) {
		return response.data;
	    });
    };
    function getLogFiles() {
	return $http.get('/api/data-files/?source_type=log')
	    .then(function(response) {
		return response.data;
	    });
    };
};
