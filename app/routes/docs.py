"""
API Documentation Routes
Serves OpenAPI specification and Swagger UI
"""
from flask import Blueprint, render_template, render_template_string, send_from_directory, current_app, flash, redirect, url_for
from app.decorators import login_required, feature_required, get_current_user
from app.models import Setting
import os
import secrets
import hashlib

docs_bp = Blueprint('docs', __name__)

# Swagger UI HTML template (uses CDN for Swagger UI assets)
SWAGGER_UI_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CryptoLens API Documentation</title>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5.9.0/swagger-ui.css">
    <style>
        body {
            margin: 0;
            padding: 0;
        }
        .swagger-ui .topbar {
            display: none;
        }
        .swagger-ui .info {
            margin: 20px 0;
        }
        .swagger-ui .info .title {
            color: #3b82f6;
        }
    </style>
</head>
<body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5.9.0/swagger-ui-bundle.js"></script>
    <script>
        window.onload = function() {
            SwaggerUIBundle({
                url: "/api/docs/openapi.yaml",
                dom_id: '#swagger-ui',
                presets: [
                    SwaggerUIBundle.presets.apis,
                    SwaggerUIBundle.SwaggerUIStandalonePreset
                ],
                layout: "BaseLayout",
                deepLinking: true,
                showExtensions: true,
                showCommonExtensions: true
            });
        };
    </script>
</body>
</html>
"""


@docs_bp.route('/docs')
def swagger_ui():
    """Serve Swagger UI for API documentation"""
    return render_template_string(SWAGGER_UI_TEMPLATE)


@docs_bp.route('/docs/openapi.yaml')
def openapi_spec():
    """Serve the OpenAPI specification file"""
    static_folder = os.path.join(current_app.root_path, 'static')
    return send_from_directory(static_folder, 'openapi.yaml', mimetype='text/yaml')


@docs_bp.route('/docs/openapi.json')
def openapi_spec_json():
    """Serve the OpenAPI specification as JSON"""
    import yaml
    import json

    static_folder = os.path.join(current_app.root_path, 'static')
    yaml_path = os.path.join(static_folder, 'openapi.yaml')

    with open(yaml_path, 'r') as f:
        spec = yaml.safe_load(f)

    return current_app.response_class(
        json.dumps(spec, indent=2),
        mimetype='application/json'
    )


@docs_bp.route('/')
@login_required
@feature_required('api_access')
def api_index():
    """API page with key management and documentation link"""
    user = get_current_user()

    # Get current API key (show masked version)
    api_key = Setting.get('api_key')
    api_key_masked = None
    if api_key:
        # Show first 4 and last 4 characters
        if len(api_key) > 8:
            api_key_masked = api_key[:4] + '*' * (len(api_key) - 8) + api_key[-4:]
        else:
            api_key_masked = '*' * len(api_key)

    return render_template('api/index.html',
                           api_key=api_key,
                           api_key_masked=api_key_masked,
                           user=user)


@docs_bp.route('/generate-key', methods=['POST'])
@login_required
@feature_required('api_access')
def generate_api_key():
    """Generate a new API key"""
    from app import db

    # Generate a secure random key
    new_key = secrets.token_urlsafe(32)

    # Store the key (plain text for display, but we could hash it)
    Setting.set('api_key', new_key)

    # Also store a hash for verification
    key_hash = hashlib.sha256(new_key.encode()).hexdigest()
    Setting.set('api_key_hash', key_hash)

    db.session.commit()

    flash('New API key generated successfully. Make sure to copy it now!', 'success')
    return redirect(url_for('docs.api_index'))


@docs_bp.route('/revoke-key', methods=['POST'])
@login_required
@feature_required('api_access')
def revoke_api_key():
    """Revoke the current API key"""
    from app import db

    Setting.set('api_key', '')
    Setting.set('api_key_hash', '')
    db.session.commit()

    flash('API key revoked. API access is now disabled.', 'warning')
    return redirect(url_for('docs.api_index'))
