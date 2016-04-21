'use strict';

angular
    .module('loom.controllers')
    .controller('RunDetailController', RunDetailController);

RunDetailController.$inject = [
    '$scope', 'DataService', '$routeParams'
];

function RunDetailController($scope, DataService, $routeParams) {
    $scope.loading = true;
    $scope.activeData = DataService.getActiveData();
    DataService.setActiveRun($routeParams.runId).then(function() {
	$scope.loading = false;
    });
};
