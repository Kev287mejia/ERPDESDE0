"""
Vistas de Infraestructura PWA Instalable (Progressive Web App).
Eternal Labs - ERP SAS Operaciones, Retail POS & Gestión de Campo.
"""
import json
from django.http import HttpResponse
from django.shortcuts import render
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
            "<rect width='512' height='512' rx='64' fill='%2318181B'/>"
            "<path d='M120 160h272v40H120zm0 88h200v40H120zm0 88h272v40H120z' fill='%23FFFFFF'/>"
            "<circle cx='380' cy='268' r='20' fill='%2310B981'/>"
            "</svg>"
        )

        manifest = {
            "name": "ERP SAS · Eternal Labs",
            "short_name": "ERP SAS",
            "description": "Sistema de Planificación de Recursos Empresariales, Punto de Venta e Ingeniería de Campo",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#FFFFFF",
            "theme_color": "#18181B",
            "orientation": "any",
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
                    "name": "Terminal POS",
                    "url": "/billing/pos/",
                    "description": "Caja y cobro rápido en mostrador"
                },
                {
                    "name": "Órdenes de Trabajo",
                    "url": "/operations/orders/",
                    "description": "Frentes de obra e ingeniería de campo"
                },
                {
                    "name": "Checklists SST",
                    "url": "/sst/",
                    "description": "Seguridad laboral y prevención Ley 618"
                }
            ]
        }
        return HttpResponse(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            content_type="application/manifest+json"
        )


class PWAServiceWorkerView(View):
    """
    Service Worker con estrategia Network First with Cache Fallback y contingencia Offline.
    Permite operar en zonas industriales sin conectividad (subestaciones, minas, carreteras).
    """
    def get(self, request, *args, **kwargs):
        sw_script = """
const CACHE_NAME = 'erp-sas-v1';
const OFFLINE_URL = '/offline/';
const PRECACHE_URLS = [
  '/',
  '/manifest.json',
  OFFLINE_URL
];

self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(PRECACHE_URLS).catch(err => {
        console.warn('[PWA-SW] Fallo precaching inicial:', err);
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

  if (request.method !== 'GET') {
    return;
  }

  // Estrategia Network-First con Fallback para navegación de campo
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then(networkResponse => {
          if (networkResponse && networkResponse.status === 200) {
            const copy = networkResponse.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(request, copy));
          }
          return networkResponse;
        })
        .catch(() => {
          return caches.match(request).then(cached => {
            return cached || caches.match(OFFLINE_URL);
          });
        })
    );
    return;
  }

  // Recursos estáticos: Cache First con Network Refresh
  event.respondWith(
    caches.match(request).then(cachedResponse => {
      if (cachedResponse) {
        fetch(request).then(networkResponse => {
          if (networkResponse && networkResponse.status === 200) {
            caches.open(CACHE_NAME).then(cache => cache.put(request, networkResponse));
          }
        }).catch(() => {});
        return cachedResponse;
      }
      return fetch(request).then(networkResponse => {
        if (networkResponse && networkResponse.status === 200) {
          const copy = networkResponse.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(request, copy));
        }
        return networkResponse;
      });
    })
  );
});
"""
        response = HttpResponse(sw_script.strip(), content_type="application/javascript")
        response['Service-Worker-Allowed'] = '/'
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response


class PwaOfflineFallbackView(View):
    """
    Vista de contingencia de campo cuando el dispositivo pierde la señal celular o conexión WiFi.
    Muestra la bitácora técnica de seguridad Ley 618 y monitor de reconexión.
    """
    template_name = 'core/offline.html'

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name)


# Aliases para compatibilidad de nomenclatura
PwaManifestView = PWAManifestView
PwaServiceWorkerView = PWAServiceWorkerView
