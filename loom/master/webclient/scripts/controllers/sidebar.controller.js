'use strict';

angular
    .module('loom.controllers')
    .controller('SidebarController', SidebarController);

SidebarController.$inject = ['$scope', '$location'];

function SidebarController($scope, $location) {
    $scope.$location = $location;
};
