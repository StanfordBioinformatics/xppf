'use strict';

angular
    .module('loom.controllers')
    .controller('StepDetailController', StepDetailController);

StepDetailController.$inject = [
    '$scope', 'DataService', '$routeParams'
];

function StepDetailController($scope, DataService, $routeParams) {
    $scope.loading = true;
    DataService.setActiveStep($routeParams.stepId).then(function() {
	$scope.loading = false;
    });
    DataService.setActiveWorkflow($routeParams.workflowId);
    $scope.activeData = DataService.getActiveData();
};
