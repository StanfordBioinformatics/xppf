'use strict';

angular
    .module('loom.controllers')
    .controller('StepRunDetailController', StepRunDetailController);

StepRunDetailController.$inject = [
    '$scope', 'DataService', '$routeParams'
];

function StepRunDetailController($scope, DataService, $routeParams) {
    $scope.loading = true;
    DataService.setActiveStepRun($routeParams.stepRunId).then(function() {
	$scope.loading = false;
    });
    DataService.setActiveRun($routeParams.runId);
    $scope.activeData = DataService.getActiveData();
};
