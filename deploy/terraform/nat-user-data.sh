#!/bin/bash
# NAT instance bootstrap: masquerade traffic from the private subnets out to the
# internet. Runs on first boot (user_data) and re-applies on every boot via a
# systemd unit so it survives reboots.
set -euxo pipefail

# AL2023 may not ship iptables; install the nft-backed iptables shim.
dnf install -y iptables-nft || dnf install -y iptables || true

echo 'net.ipv4.ip_forward=1' > /etc/sysctl.d/99-nat.conf
sysctl -p /etc/sysctl.d/99-nat.conf || sysctl -w net.ipv4.ip_forward=1

cat > /usr/local/sbin/nat-setup.sh <<'SCRIPT'
#!/bin/bash
set -e
sysctl -w net.ipv4.ip_forward=1
IFACE=$(ip route show default | awk '{print $5; exit}')
iptables -t nat -C POSTROUTING -o "$IFACE" -j MASQUERADE 2>/dev/null || iptables -t nat -A POSTROUTING -o "$IFACE" -j MASQUERADE
iptables -C FORWARD -i "$IFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || iptables -A FORWARD -i "$IFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT
iptables -C FORWARD -o "$IFACE" -j ACCEPT 2>/dev/null || iptables -A FORWARD -o "$IFACE" -j ACCEPT
SCRIPT
chmod +x /usr/local/sbin/nat-setup.sh

cat > /etc/systemd/system/nat.service <<'UNIT'
[Unit]
Description=NAT masquerade for private subnets
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/nat-setup.sh
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now nat.service
