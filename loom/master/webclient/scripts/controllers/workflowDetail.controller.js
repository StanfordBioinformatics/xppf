'use strict';

angular
    .module('loom.controllers')
    .controller('WorkflowDetailController', WorkflowDetailController);

WorkflowDetailController.$inject = [
    '$scope', 'DataService', '$routeParams'
];

function WorkflowDetailController($scope, DataService, $routeParams) {
    $scope.loading = true;
    $scope.activeData = DataService.getActiveData();
    DataService.setActiveWorkflow($routeParams.workflowId).then(function() {
	$scope.loading = false;
    });
};
