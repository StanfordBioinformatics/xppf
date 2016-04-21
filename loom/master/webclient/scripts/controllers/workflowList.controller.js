'use strict';

angular
    .module('loom.controllers')
    .controller('WorkflowListController', WorkflowListController);

WorkflowListController.$inject = ['$scope', 'DataService'];

function WorkflowListController($scope, DataService){
    $scope.loading = true;
    DataService.getWorkflows().then(function(workflows) {
	$scope.loading = false;
	$scope.workflows = workflows;
    });
};
