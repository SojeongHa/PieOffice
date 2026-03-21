#!/bin/bash
# generate-mobileconfig.sh — Create a signed .mobileconfig profile
# that bundles CA trust + client identity for iPhone installation.
# Result: single file, shows as "Signed" in iOS, one-step install.
set -euo pipefail

TLS_DIR="$HOME/.pieoffice-tls"
OUTPUT="$TLS_DIR/PieOffice.mobileconfig"
UNSIGNED="$TLS_DIR/_unsigned.mobileconfig"
CLIENT_P12_PASSWORD="pieoffice"

# Check prerequisites
for f in ca.pem ca-key.pem client.p12 client-cert.pem; do
    if [ ! -f "$TLS_DIR/$f" ]; then
        echo "Missing: $TLS_DIR/$f — run setup-terminal.sh first"
        exit 1
    fi
done

# Base64-encode the client .p12 and CA cert
CLIENT_P12_B64=$(base64 < "$TLS_DIR/client.p12")
CA_PEM_B64=$(base64 < "$TLS_DIR/ca.pem")

# Generate UUIDs for profile
PROFILE_UUID=$(uuidgen)
CA_PAYLOAD_UUID=$(uuidgen)
IDENTITY_PAYLOAD_UUID=$(uuidgen)

cat > "$UNSIGNED" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>PayloadContent</key>
    <array>
        <dict>
            <key>PayloadCertificateFileName</key>
            <string>PieOffice CA</string>
            <key>PayloadContent</key>
            <data>$CA_PEM_B64</data>
            <key>PayloadDescription</key>
            <string>Adds the PieOffice CA certificate</string>
            <key>PayloadDisplayName</key>
            <string>PieOffice CA</string>
            <key>PayloadIdentifier</key>
            <string>com.pieoffice.ca.$CA_PAYLOAD_UUID</string>
            <key>PayloadType</key>
            <string>com.apple.security.root</string>
            <key>PayloadUUID</key>
            <string>$CA_PAYLOAD_UUID</string>
            <key>PayloadVersion</key>
            <integer>1</integer>
        </dict>
        <dict>
            <key>PayloadCertificateFileName</key>
            <string>PieOffice Client</string>
            <key>PayloadContent</key>
            <data>$CLIENT_P12_B64</data>
            <key>PayloadDescription</key>
            <string>Adds the PieOffice client identity</string>
            <key>PayloadDisplayName</key>
            <string>PieOffice Client Identity</string>
            <key>PayloadIdentifier</key>
            <string>com.pieoffice.identity.$IDENTITY_PAYLOAD_UUID</string>
            <key>PayloadType</key>
            <string>com.apple.security.pkcs12</string>
            <key>PayloadUUID</key>
            <string>$IDENTITY_PAYLOAD_UUID</string>
            <key>PayloadVersion</key>
            <integer>1</integer>
            <key>Password</key>
            <string>$CLIENT_P12_PASSWORD</string>
        </dict>
    </array>
    <key>PayloadDescription</key>
    <string>Installs PieOffice CA trust and client certificate for remote terminal access.</string>
    <key>PayloadDisplayName</key>
    <string>PieOffice Remote Terminal</string>
    <key>PayloadIdentifier</key>
    <string>com.pieoffice.remote.$PROFILE_UUID</string>
    <key>PayloadOrganization</key>
    <string>PieOffice</string>
    <key>PayloadRemovalDisallowed</key>
    <false/>
    <key>PayloadType</key>
    <string>Configuration</string>
    <key>PayloadUUID</key>
    <string>$PROFILE_UUID</string>
    <key>PayloadVersion</key>
    <integer>1</integer>
    <key>ConsentText</key>
    <dict>
        <key>default</key>
        <string>This profile installs the PieOffice CA and client certificate for secure remote terminal access from your phone.</string>
    </dict>
</dict>
</plist>
PLIST

# Sign the profile with our CA
openssl smime -sign \
    -signer "$TLS_DIR/ca.pem" \
    -inkey "$TLS_DIR/ca-key.pem" \
    -certfile "$TLS_DIR/ca.pem" \
    -nodetach \
    -outform der \
    -in "$UNSIGNED" \
    -out "$OUTPUT" \
    2>/dev/null

rm -f "$UNSIGNED"

echo "Generated: $OUTPUT"
echo ""
echo "AirDrop this single file to your iPhone."
echo "It bundles CA trust + client certificate."
echo "iPhone will show: Signed by 'PieOffice CA'"
