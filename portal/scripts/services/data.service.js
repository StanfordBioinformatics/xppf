(function () {
   'use strict';

    angular
	.module("loom.services")
	.service("DataService", DataService)

    DataService.$inject = ["$http", "$q"];

    function DataService($http, $q) {
	/* DataService retrieves and caches data from the server. */

	this.setActiveRun = setActiveRun;
	this.setActiveTask = setActiveTask;
	this.setActiveTaskAttempt = setActiveTaskAttempt;
	this.setActiveTemplate = setActiveTemplate;
	this.setActiveFile = setActiveFile;
	this.getAllActive = getAllActive;
	this.getRunDetail = getRunDetail;
	this.getRuns = getRuns;
	this.getTemplates = getTemplates;
	this.getImportedFiles = getImportedFiles;
	this.getResultFiles = getResultFiles;
	this.getLogFiles = getLogFiles;
	this.getLoginAndVersionInfo = getLoginAndVersionInfo;

	var activeData = {};

	function getAllActive() {
            return activeData;
	}

	function setActiveRun(runId) {
            return $http.get("/api/runs/" + runId + "/")
		.then(function(response) {
		    activeData.run = response.data;
		    expandDataChannels(activeData.run.inputs);
		    expandDataChannels(activeData.run.outputs);
		});
	}

	function setActiveTask(taskId) {
            return $http.get("/api/tasks/" + taskId + "/")
		.then(function(response) {
		    activeData.task = response.data;
		    expandDataChannels(activeData.task.inputs);
		    expandDataChannels(activeData.task.outputs);
		});
	}

	function setActiveTaskAttempt(taskAttemptId) {
            return $http.get("/api/task-attempts/" + taskAttemptId + "/")
		.then(function(response) {
		    activeData.taskAttempt = response.data;
		    expandDataChannels(activeData.taskAttempt.inputs);
		    expandDataChannels(activeData.taskAttempt.outputs);
		});
	}

	function setActiveTemplate(templateId) {
            return $http.get("/api/templates/" + templateId + "/")
		.then(function(response) {
		    activeData.template = response.data;
		    expandDataChannels(activeData.template.inputs);
		    expandDataChannels(activeData.template.outputs);
		});
	}

	function expandDataChannels(channels) {
	    if (channels) {
		if (channels==null){
		    return;
		}
		for (var i=0; i < channels.length; i++) {
		    expandDataChannel(channels[i]);
		}
	    }
	}

	function expandDataChannel(channel) {
	    if (channel.data==null){
		return;
	    }
            return $http.get(
		"/api/data-nodes/"+channel.data.uuid+"?expand")
		.then(function(response) {
		    channel.data = response.data;
		});
	}

	function setActiveFile(fileId) {
            return $http.get("/api/data-objects/" + fileId + "/")
		.then(function(response) {
		    activeData.file = response.data;
		});
	}

	function getRunDetail(runId) {
	    return $http.get("/api/runs/" + runId + "/")
		.then(function(response) {
		    return response.data;
		});
	}
	function getRuns(limit, offset) {
            return $http.get("/api/runs/?parent_only&limit="+limit+"&offset="+offset)
		.then(function(response) {
		    return response.data;
		});
	}

	function getTemplates(limit, offset) {
            return $http.get("/api/templates/?imported&limit="+limit+"&offset="+offset)
		.then(function(response) {
		    return response.data;
		});
	}

	function getImportedFiles(limit, offset) {
            return $http.get("/api/data-objects/?source_type=imported&type=file&limit="+limit+"&offset="+offset)
		.then(function(response) {
		    return response.data;
		});
	}

	function getResultFiles(limit, offset) {
            return $http.get("/api/data-objects/?source_type=result&type=file&limit="+limit+"&offset="+offset)
		.then(function(response) {
		    return response.data;
		});
	}

	function getLogFiles(limit, offset) {
            return $http.get("/api/data-objects/?source_type=log&type=file&limit="+limit+"&offset="+offset)
		.then(function(response) {
		    return response.data;
		});
	}

	function getLoginAndVersionInfo() {
	    return $http.get("/api/info/")
		.then(function(response) {
		    activeData.username = response.data.username;
		    activeData.loginRequired = response.data.login_required;
		    activeData.version = response.data.version
		});
	}
    }
}());
