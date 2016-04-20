'use strict';

angular
    .module('loom', [
	'loom.routes',
	'loom.controllers',
	'loom.services',
    ]);

angular
    .module('loom.routes', ['ngRoute']);

angular
    .module('loom.controllers', ['loom.services']);

angular
    .module('loom.services', []);
