'use strict';

angular
    .module('loom.routes')
    .config(config);

config.$inject = ['$routeProvider'];

function config($routeProvider) {

    $routeProvider
        .when('/runs/:runId/steps/:stepRunId', {
            templateUrl: 'views/step-run-detail.html',
            controller: 'StepRunDetailController'
        })
        .when('/runs/:runId', {
            templateUrl: 'views/run-detail.html',
            controller: 'RunDetailController'
        })
        .when('/runs', {
            templateUrl: 'views/run-list.html',
            controller: 'RunListController'
        })
        .when('/workflows', {
            templateUrl: 'views/workflow-list.html',
            controller: 'WorkflowListController'
        })
        .when('/workflows/:workflowId', {
            templateUrl: 'views/workflow-detail.html',
            controller: 'WorkflowDetailController'
        })
        .when('/workflows/:workflowId/steps/:stepId', {
            url: '/steps/{stepId}',
            templateUrl: 'views/step-detail.html',
            controller: 'StepDetailController'
        })
        .when('/files', {
            templateUrl: 'views/file-list.html',
            controller: 'FileListController'
        })
        .when('/files/:fileId', {
            templateUrl: 'views/file-detail.html',
            controller: 'FileDetailController'
        })
	.otherwise('/runs');
};
