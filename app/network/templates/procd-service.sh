#!/bin/sh /etc/rc.common
START=95
STOP=10
USE_PROCD=1
start_service() {
 procd_open_instance main
 procd_set_param command /usr/lib/smooth-caddy/manage run
 procd_set_param user root
 procd_set_param respawn 3600 1 5
 procd_set_param stdout 1
 procd_set_param stderr 1
 procd_close_instance
}
