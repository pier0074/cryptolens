"""
API Documentation Routes
Serves OpenAPI specification and Swagger UI
"""
from flask import Blueprint, render_template_string, send_from_directory, current_app
import os

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
