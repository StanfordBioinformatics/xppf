'use strict';

angular
    .module('loom.controllers')
    .controller('BreadcrumbController', BreadcrumbController);

BreadcrumbController.$inject = ['$scope', 'DataService', '$location', '$routeParams'];

function BreadcrumbController($scope, DataService, $location, $routeParams) {
    $scope.$location = $location;
    $scope.params = $routeParams;
    $scope.activeData = DataService.getActiveData();
};
