(function () {
   'use strict';

angular
    .module('loom.controllers')
    .controller('VersionController', VersionController);

VersionController.$inject = [
    '$scope', 'DataService'
];

function VersionController($scope, DataService) {
    DataService.getLoginAndVersionInfo().then(function() {
	$scope.version = DataService.getAllActive().version
    });
};
}());
