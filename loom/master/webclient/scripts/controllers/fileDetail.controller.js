'use strict';

angular
    .module('loom.controllers')
    .controller('FileDetailController', FileDetailController);

FileDetailController.$inject = [
    '$scope', 'DataService', '$routeParams'
];

function FileDetailController($scope, DataService, $routeParams) {
    $scope.activeData = DataService.getActiveData();
    $scope.loading = true;
    DataService.setActiveFile($routeParams.fileId).then(function() {
	$scope.loading = false;
    });
};
