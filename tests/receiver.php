<?php
// Minimal WordPress harness: verifies protocol semantics, not a full WP deployment.
define('ABSPATH', __DIR__ . '/');
define('SITEPULSE_SHIELD_SECRET', str_repeat('s', 32));
$hooks = array(); $route = null; $transients = array(); $options = array();
function add_action($name,$fn){global $hooks;$hooks[$name]=$fn;}
function register_rest_route($ns,$path,$args){global $route;$route=$args;}
function get_transient($name){global $transients;return $transients[$name]??false;}
function set_transient($name,$value,$ttl){global $transients;$transients[$name]=$value;}
function update_option($name,$value,$autoload){global $options;$options[$name]=$value;}
function sanitize_key($value){return preg_replace('/[^a-z0-9_-]/','',strtolower($value));}
class WP_Error {function __construct(public $code,public $message,public $data){}}
class WP_REST_Response {function __construct(public $data,public $status){}}
class Request {
    function __construct(public $body,public $signature){}
    function get_body(){return $this->body;}
    function get_header($name){return $this->signature;}
    function get_json_params(){return json_decode($this->body,true);}
}
function check($condition,$message){if(!$condition)throw new Exception($message);}
require __DIR__.'/../integrations/wordpress/sitepulse-shield.php';
$hooks['rest_api_init']();
$body=json_encode(array('event'=>'suspend','event_id'=>'unique-1','occurred_at'=>gmdate('c')));
$request=new Request($body,'sha256='.hash_hmac('sha256',$body,SITEPULSE_SHIELD_SECRET));
check(($route['permission_callback'])($request)===true,'Valid signature rejected');
check(($route['permission_callback'])(new Request($body,'bad'))===false,'Invalid signature accepted');
$response=($route['callback'])($request);
check($response->data['state']==='suspend','Suspend not acknowledged');
check($options['sitepulse_shield_state']==='suspend','State not persisted');
check(($route['callback'])($request) instanceof WP_Error,'Replay accepted');
$old=new Request(json_encode(array('event'=>'resume','event_id'=>'unique-2','occurred_at'=>'2020-01-01T00:00:00Z')),'');
check(($route['callback'])($old) instanceof WP_Error,'Stale event accepted');
echo "Receiver signature, replay, timestamp and state checks passed\n";
