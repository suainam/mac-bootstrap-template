#!/bin/sh
# Generate an internal CA and a server certificate for code-server HTTPS.
set -e

CERT_IP="${CODE_SERVER_CERT_IP:-10.0.103.217}"

# Install openssl if not present
if ! command -v openssl >/dev/null 2>&1; then
    apk add --no-cache openssl
fi

mkdir -p /etc/nginx/ssl

needs_regen=0
if [ ! -f /etc/nginx/ssl/ca.crt ] || [ ! -f /etc/nginx/ssl/ca.key ] || \
   [ ! -f /etc/nginx/ssl/cert.pem ] || [ ! -f /etc/nginx/ssl/key.pem ]; then
    needs_regen=1
elif ! openssl x509 -in /etc/nginx/ssl/ca.crt -noout -ext keyUsage 2>/dev/null | grep -q "Certificate Sign"; then
    needs_regen=1
elif ! openssl x509 -in /etc/nginx/ssl/cert.pem -noout -ext subjectAltName 2>/dev/null | grep -q "IP Address:${CERT_IP}"; then
    needs_regen=1
elif ! openssl x509 -in /etc/nginx/ssl/cert.pem -noout -ext extendedKeyUsage 2>/dev/null | grep -q "TLS Web Server Authentication"; then
    needs_regen=1
fi

if [ "$needs_regen" = "1" ]; then
    echo "Generating code-server internal CA and server certificate for ${CERT_IP}..."
    tmpdir="$(mktemp -d)"
    trap 'rm -rf "$tmpdir"' EXIT

    openssl genrsa -out /etc/nginx/ssl/ca.key 4096
    openssl req -x509 -new -nodes \
        -key /etc/nginx/ssl/ca.key \
        -sha256 \
        -days 3650 \
        -out /etc/nginx/ssl/ca.crt \
        -subj "/CN=code-server-local-ca" \
        -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
        -addext "keyUsage=critical,keyCertSign,cRLSign" \
        -addext "subjectKeyIdentifier=hash"

    openssl genrsa -out /etc/nginx/ssl/key.pem 4096
    openssl req -new \
        -key /etc/nginx/ssl/key.pem \
        -out "$tmpdir/server.csr" \
        -subj "/CN=${CERT_IP}"

    cat > "$tmpdir/server.ext" <<EOF
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=IP:${CERT_IP}
EOF

    openssl x509 -req \
        -in "$tmpdir/server.csr" \
        -CA /etc/nginx/ssl/ca.crt \
        -CAkey /etc/nginx/ssl/ca.key \
        -CAcreateserial \
        -out /etc/nginx/ssl/cert.pem \
        -days 825 \
        -sha256 \
        -extfile "$tmpdir/server.ext"

    chmod 600 /etc/nginx/ssl/ca.key /etc/nginx/ssl/key.pem
    chmod 644 /etc/nginx/ssl/ca.crt /etc/nginx/ssl/cert.pem
    echo "Certificate generated."
fi

exec nginx -g "daemon off;"
