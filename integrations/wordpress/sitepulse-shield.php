<?php
/**
 * Plugin Name: SitePulse Shield
 * Description: Owner-installed, signed maintenance-mode receiver for SitePulse.
 * Version: 0.2.0
 */
if (!defined('ABSPATH')) exit;
add_action('rest_api_init', function () {
    register_rest_route('sitepulse/v1', '/shield', array(
        'methods' => 'POST',
        'permission_callback' => function ($request) {
            if (!defined('SITEPULSE_SHIELD_SECRET') || strlen(SITEPULSE_SHIELD_SECRET) < 32) return false;
            $expected = 'sha256=' . hash_hmac('sha256', $request->get_body(), SITEPULSE_SHIELD_SECRET);
            return hash_equals($expected, (string)$request->get_header('x-sitepulse-signature'));
        },
        'callback' => function ($request) {
            $body = $request->get_json_params();
            $timestamp = strtotime($body['occurred_at'] ?? '');
            $event = $body['event'] ?? '';
            $id = sanitize_key($body['event_id'] ?? '');
            if (!$timestamp || abs(time() - $timestamp) > 300 || !$id || !in_array($event, array('suspend','resume','inventory'), true)) {
                return new WP_Error('invalid_event', 'Invalid or stale event', array('status'=>400));
            }
            if (get_transient('sitepulse_' . $id)) {
                return new WP_Error('replayed_event', 'Event already used', array('status'=>409));
            }
            set_transient('sitepulse_' . $id, 1, 600);
            if ($event === 'inventory') {
                require_once ABSPATH . 'wp-admin/includes/plugin.php';
                $updates = get_site_transient('update_plugins');
                $items = array();
                foreach (get_plugins() as $file => $plugin) {
                    $update = is_object($updates) && isset($updates->response[$file]) ? $updates->response[$file] : null;
                    $items[] = array('name'=>$plugin['Name'], 'version'=>$plugin['Version'], 'active'=>is_plugin_active($file), 'update_available'=>(bool)$update, 'new_version'=>$update ? $update->new_version : null);
                }
                return new WP_REST_Response(array('state'=>'inventory','plugins'=>$items,'updates_checked_at'=>is_object($updates) ? ($updates->last_checked ?? null) : null),200);
            }
            update_option('sitepulse_shield_state', $event, false);
            return new WP_REST_Response(array('state'=>$event),200);
        }
    ));
});
add_action('template_redirect', function () {
    if (get_option('sitepulse_shield_state') !== 'suspend' || current_user_can('manage_options')) return;
    status_header(503);
    nocache_headers();
    header('Retry-After: 3600');
    wp_die(esc_html__('This website is temporarily unavailable. Please contact the site owner.', 'sitepulse'), 'Temporarily unavailable', array('response'=>503));
});
