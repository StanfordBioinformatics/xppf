(function (){
    'use strict';

    angular.module('loom.controllers').
	controller('AuthController', AuthController);

    AuthController.$inject = ['$scope', 'DataService', '$resource', '$window'];
    
    function AuthController($scope, DataService, $resource, $window) {
            // Angular does not detect auto-fill or auto-complete. If the browser
            // autofills "username", Angular will be unaware of this and think
            // the $scope.username is blank. To workaround this we use the
            // autofill-event polyfill [4][5]
            $('#id_auth_form input').checkAndTriggerAutoFillEvent();

	$scope.activeData = DataService.getAllActive();
	DataService.getLoginAndVersionInfo();
        $scope.getCredentials = function(){
	    return {username: $scope.username, password: $scope.password};
        }
	    
	function get_auth_header(data){
	    // as per HTTP authentication spec [1], credentials must be
	    // encoded in base64. Lets use window.btoa [2]
	    return 'Basic ' + btoa(data.username + ':' + data.password);
        }

        $scope.login = function(){
	    function get_login_resource(credentials) {
		return $resource('/api/auth\\/', {}, {
		    login: {method: 'POST', headers: {
			'Authorization': get_auth_header(credentials)
		    }}
		})
	    }
	    get_login_resource($scope.getCredentials()).login()
		.$promise
                .then(function(data){
		    // on good username and password
		    DataService.getLoginAndVersionInfo();
		    $window.location = '#/runs';
                })
                .catch(function(data){
		    // on incorrect username and password
		    alert(data.data.detail);
                });
        }

        $scope.logout = function(){
	    function get_logout_resource() {
		return $resource('/api/auth\\/', {}, {
		    logout: {method: 'DELETE'}
		})
	    }
	    get_logout_resource().logout()
		.$promise
		.then(function(){
		    $scope.logged_in_as = undefined;
		    $window.location = '#/login';
		});
        }
    }

}());

// [1] https://tools.ietf.org/html/rfc2617
// [2] https://developer.mozilla.org/en-US/docs/Web/API/Window.btoa
// [3] https://docs.djangoproject.com/en/dev/ref/settings/#append-slash
// [4] https://github.com/tbosch/autofill-event
// [5] http://remysharp.com/2010/10/08/what-is-a-polyfill/

// https://richardtier.com/2014/03/15/authenticate-using-django-rest-framework-endpoint-and-angularjs/

