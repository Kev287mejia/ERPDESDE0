"""
Vistas de Infraestructura PWA Instalable (Progressive Web App).
Eternal Labs - ERP SAS Operaciones & Gestión de Campo.
"""
import json
from django.http import HttpResponse
from django.views import View


class PWAManifestView(View):
    """
    Especificación de manifiesto PWA (application/manifest+json).
    Permite la instalación en pantalla de inicio de teléfonos móviles y tablets Android / iOS.
    """
    def get(self, request, *args, **kwargs):
        icon_svg = (
            "data:image/svg+xml;utf8,"
            "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 512 512' width='512' height='512'>"
            "<rect width='512' height='512' rx='64' fill='%230f172a'/>"
            "<path d='M120 160h272v48H120zm0 96h200v48H120zm0 96h272v48H120z' fill='%2338bdf8'/>"
            "<circle cx='380' cy='280' r='24' fill='%2310b981'/>"
            "</svg>"
        )

        manifest = {
            "name": "ERP SAS · Operaciones & Gestión",
            "short_name": "ERP SAS",
            "description": "Sistema de Gestión Empresarial B2B e Ingeniería de Campo",
            "start_url": "/operations/orders/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#0F172A",
            "theme_color": "#0F172A",
            "orientation": "portrait-primary",
            "icons": [
                {
                    "src": icon_svg,
                    "sizes": "192x192 512x512",
                    "type": "image/svg+xml",
                    "purpose": "any maskable"
                }
            ],
            "shortcuts": [
                {
                    "name": "Mis Órdenes de Trabajo",
                    "url": "/operations/orders/",
                    "description": "Acceso directo a OTs activas"
                },
                {
                    "name": "Almacén & Kardex",
                    "url": "/inventory/dashboard/",
                    "description": "Existencias y despachos"
                }
            ]
        }
        return HttpResponse(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            content_type="application/manifest+json"
        )


class PWAServiceWorkerView(View):
    """
    Service Worker con estrategia Network First with Cache Fallback.
    Permite operar en zonas industriales sin conectividad (subestaciones, minas, plantas).
    """
    def get(self, request, *args, **kwargs):
        sw_script = """
const CACHE_NAME = 'erp-sas-v1';
const PRECACHE_URLS = [
  '/operations/orders/',
  '/manifest.json'
];

self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(PRECACHE_URLS).catch(err => {
        console.warn('[PWA-SW] Pre-caching warning:', err);
      });
    })
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const request = event.request;

  // No interceptar peticiones no GET ni peticiones API externas
  if (request.method !== 'GET') {
    return;
  }

  // Estrategia Network First con Cache Fallback
  event.respondWith(
    fetch(request)
      .then(networkResponse => {
        if (networkResponse && networkResponse.status === 200) {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then(cache => {
            cache.put(request, responseToCache);
          });
        }
        return networkResponse;
      })
      .catch(() => {
        return caches.match(request).then(cachedResponse => {
          if (cachedResponse) {
            return cachedResponse;
          }
          // Si es navegación HTML y no hay red ni cache, devolver página offline o raíz de OTs
          if (request.headers.get('accept') && request.headers.get('accept').includes('text/html')) {
            return caches.match('/operations/orders/');
          }
        });
      })
  );
});
"""
        response = HttpResponse(sw_script.strip(), content_type="application/javascript")
        response['Service-Worker-Allowed'] = '/'
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response
