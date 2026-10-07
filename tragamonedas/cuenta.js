/* =====================================================================
   RuletonPeliculon — cuenta.js
   La sesión de todas las pantallas vive aquí (antes cada pantalla traía
   su propia copia):

     - Sesión anónima: se crea sola la primera vez que hace falta.
     - "Continuar con Google": los swipes anónimos se pasan a la cuenta
       (ver 14_cuentas.sql) para que no se pierdan y sigan a la persona
       en cualquier dispositivo.
     - El botón de cuenta (arriba a la derecha) se dibuja solo.

   Las pantallas usan:
     Cuenta.sesion()        → asegura que haya sesión (anónima o con cuenta)
     Cuenta.rpc(fn, args)   → llama una función de Supabase con esa sesión
     Cuenta.usuario()       → el usuario actual o null
     Cuenta.entrar() / Cuenta.salir() / Cuenta.borrar()
   y pueden escuchar el evento  window "cuenta:cambio".

   Necesita que supabase.js se cargue ANTES que este archivo.
   ===================================================================== */
(function () {
  'use strict';

  var CONFIG = {
    url: 'https://mlrezhasoubggrembngu.supabase.co',
    // Publishable key: sí puede ir en el frontend. NUNCA pongas aquí la secret key.
    key: 'sb_publishable_aMwHv2EdEELy5FRcRdkYDg_ipcSNSTG',
    proveedor: 'google',
    privacidad: 'privacidad.html'
  };
  var VIEJA = 'ruleta_sesion_v1';   // sesión anónima de la versión anterior (se migra una sola vez)
  var PASE = 'ruleta_pase_v1';      // pase para pasar los swipes anónimos a la cuenta

  function leer(k) { try { return localStorage.getItem(k); } catch (_) { return null; } }
  function guardar(k, v) { try { localStorage.setItem(k, v); } catch (_) {} }
  function quitar(k) { try { localStorage.removeItem(k); } catch (_) {} }

  // Sin respuesta del servidor (o error 5xx): se puede reintentar; no es que la sesión esté mal.
  function esDeRed(e) {
    if (!e) return false;
    if (e.name === 'AuthRetryableFetchError') return true;
    var s = e.status;
    return s === 0 || s === undefined || s === null || s >= 500;
  }

  // ------------------------------------------------------------------
  // 1. Si Google regresó con error (por ejemplo, la persona canceló), se
  //    limpia la dirección antes de que nadie más la lea. La sesión que
  //    ya había se queda como estaba.
  // ------------------------------------------------------------------
  var regreso = (function () {
    try {
      var q = new URLSearchParams(location.search);
      var h = new URLSearchParams(location.hash.replace(/^#/, ''));
      var codigo = q.get('error_code') || h.get('error_code') || q.get('error') || h.get('error');
      if (!codigo) return null;
      var enHash = h.has('error') || h.has('error_code') || h.has('error_description');
      ['error', 'error_code', 'error_description'].forEach(function (k) { q.delete(k); });
      var limpia = location.pathname + (q.toString() ? '?' + q.toString() : '') + (enHash ? '' : location.hash);
      history.replaceState(history.state, '', limpia);
      return { codigo: codigo };
    } catch (_) { return null; }
  })();

  var sb = null;
  if (window.supabase && window.supabase.createClient) {
    sb = window.supabase.createClient(CONFIG.url, CONFIG.key, {
      auth: { flowType: 'pkce', persistSession: true, autoRefreshToken: true, detectSessionInUrl: true }
    });
  } else {
    console.error('cuenta.js: falta cargar supabase.js antes de este archivo');
  }

  var estado = { lista: false, usuario: null, ocupado: false };

  function avisar() {
    try { window.dispatchEvent(new CustomEvent('cuenta:cambio', { detail: { usuario: estado.usuario } })); } catch (_) {}
    pintar();
  }

  // ------------------------------------------------------------------
  // 2. Arranque: recupera la sesión, migra la de la versión anterior y,
  //    si la persona acaba de entrar con Google, le pasa sus swipes.
  // ------------------------------------------------------------------
  var inicio = null;
  function asegurarInicio() {
    if (!inicio) inicio = iniciar().catch(function (e) { inicio = null; throw e; });
    return inicio;
  }

  async function iniciar() {
    if (!sb) throw new Error('No se pudo cargar la librería de sesión (supabase.js)');
    var r = await sb.auth.getSession();
    if (r.error && esDeRed(r.error)) throw r.error;
    var ses = (r.data && r.data.session) || null;

    // Sesión anónima guardada por la versión anterior de las pantallas
    var vieja = leer(VIEJA);
    if (vieja && ses) quitar(VIEJA);
    if (vieja && !ses) {
      var v = null;
      try { v = JSON.parse(vieja); } catch (_) {}
      if (v && v.access_token && v.refresh_token) {
        var m = await sb.auth.setSession({ access_token: v.access_token, refresh_token: v.refresh_token });
        if (m.error) {
          if (esDeRed(m.error)) throw m.error;      // se reintenta después; no se pierde la sesión vieja
          quitar(VIEJA);                             // ya no servía
        } else {
          ses = m.data.session;
          quitar(VIEJA);
        }
      } else {
        quitar(VIEJA);
      }
    }

    // Regreso de Google: pasar los swipes anónimos a la cuenta
    var pase = leer(PASE);
    if (pase && ses && !ses.user.is_anonymous) {
      var f = await sb.rpc('fusionar_con_pase', { p_pase: pase });
      if (!f.error) {
        quitar(PASE);
        if (f.data && f.data.fusionado && f.data.movidas > 0) {
          mensaje(f.data.movidas === 1
            ? 'Listo: tu película calificada ya está en tu cuenta.'
            : 'Listo: tus ' + f.data.movidas + ' películas calificadas ya están en tu cuenta.');
        }
      } else if (f.status && f.status < 500) {
        quitar(PASE);                                // el servidor lo rechazó; no tiene caso reintentar
        console.warn('cuenta.js: no se pudieron pasar los swipes', f.error);
      }                                              // sin conexión: el pase se queda para el siguiente intento
    }

    if (regreso) {
      mensaje(regreso.codigo === 'access_denied'
        ? 'No entraste con Google. Tu progreso sigue aquí.'
        : 'No se pudo iniciar sesión. Tu progreso sigue aquí; intenta de nuevo.');
      regreso = null;
    }

    estado.usuario = ses ? ses.user : null;
    estado.lista = true;
    avisar();
    return ses;
  }

  if (sb) {
    // Ojo: aquí dentro no se llama a nada de sb (la librería lo pide así); solo se actualiza la vista.
    sb.auth.onAuthStateChange(function (_evento, ses) {
      estado.usuario = ses ? ses.user : null;
      setTimeout(avisar, 0);
    });
  }

  // ------------------------------------------------------------------
  // 3. Lo que usan las pantallas
  // ------------------------------------------------------------------
  var creando = null;
  async function sesion() {
    await asegurarInicio();
    var r = await sb.auth.getSession();
    if (r.data && r.data.session) return r.data.session;
    // Nunca se cambia una sesión por una anónima nueva solo porque falló la red
    if (r.error && esDeRed(r.error)) throw r.error;
    if (!creando) {
      creando = sb.auth.signInAnonymously().then(
        function (x) { creando = null; return x; },
        function (e) { creando = null; throw e; });
    }
    var a = await creando;
    if (a.error) throw a.error;
    return a.data.session;
  }

  async function rpc(fn, args, reintento) {
    await sesion();
    var r = await sb.rpc(fn, args || {});
    if (r.error) {
      // La cuenta de esta sesión ya no existe (se borró desde otro dispositivo): empezar de cero
      if (!reintento && r.error.code === '23503' && /usuarios/.test(r.error.message || '')) {
        await sb.auth.signOut({ scope: 'local' });
        return rpc(fn, args, true);
      }
      var e = new Error(fn + ' ' + r.status + ': ' + (r.error.message || 'error'));
      e.status = r.status; e.code = r.error.code;
      throw e;
    }
    return r.data;
  }

  async function entrar() {
    await asegurarInicio();
    var r = await sb.auth.getSession();
    if (r.error && esDeRed(r.error)) throw r.error;
    var ses = r.data && r.data.session;
    if (ses && ses.user.is_anonymous) {
      var p = await sb.rpc('crear_pase_fusion');
      if (p.error || !p.data) throw new Error('No se pudo preparar el traspaso de tus swipes');
      guardar(PASE, p.data);
    } else {
      quitar(PASE);
    }
    var o = await sb.auth.signInWithOAuth({
      provider: CONFIG.proveedor,
      options: { redirectTo: location.origin + location.pathname, queryParams: { prompt: 'select_account' } }
    });
    if (o.error) throw o.error;                      // si todo va bien, el navegador ya se fue a Google
  }

  async function salir() {
    await asegurarInicio();
    await sb.auth.signOut({ scope: 'local' });       // solo este dispositivo
    quitar(PASE);
    location.reload();
  }

  async function borrar() {
    await rpc('borrar_mi_cuenta');
    try { await sb.auth.signOut({ scope: 'local' }); } catch (_) {}
    quitar(PASE);
    location.reload();
  }

  window.Cuenta = {
    sesion: sesion,
    rpc: rpc,
    entrar: entrar,
    salir: salir,
    borrar: borrar,
    lista: asegurarInicio,
    usuario: function () { return estado.usuario; },
    conCuenta: function () { return !!(estado.usuario && !estado.usuario.is_anonymous); }
  };

  // ------------------------------------------------------------------
  // 4. El botón de cuenta. Vive en su propio rincón (Shadow DOM) para no
  //    mezclarse con los estilos ni con el contenido de cada pantalla.
  // ------------------------------------------------------------------
  var ui = { raiz: null, sombra: null, abierto: false, confirmar: false, texto: null, reloj: null, error: null };

  // En pantallas angostas el botón va en una franja propia arriba de todo (así nunca
  // tapa el menú); en pantallas anchas flota en la esquina, en el hueco sobre el menú.
  // z-index 50: por debajo de las ventanas de detalle de las pantallas (60).
  var CSS = [
    ':host{all:initial;display:block}',
    '*{box-sizing:border-box}',
    '.caja{position:relative;z-index:50;display:flex;justify-content:flex-end;padding:8px 10px 0;',
    '  font-family:"Barlow",system-ui,sans-serif;color:#e8eaf2}',
    '.flota{position:absolute;top:calc(100% + 8px);right:10px;z-index:1}',
    '@media (min-width:900px){.caja{position:absolute;top:10px;right:10px;padding:0}.flota{right:0}}',
    '.chip{height:34px;min-width:34px;padding:0 13px;border-radius:999px;border:1px solid rgba(196,181,240,.45);background:rgba(12,17,34,.92);',
    '  color:#e8eaf2;font:600 13px/1 "Barlow Condensed","Barlow",system-ui,sans-serif;letter-spacing:1.4px;text-transform:uppercase;cursor:pointer;',
    '  display:flex;align-items:center;justify-content:center;gap:8px}',
    '.chip:hover{border-color:#c4b5f0;color:#fff}',
    '.chip:focus-visible,.btn:focus-visible,.liga:focus-visible{outline:2px solid #c4b5f0;outline-offset:2px}',
    '.chip.foto{padding:0;width:34px;overflow:hidden;background:#c4b5f0;color:#0c1122;border-color:rgba(196,181,240,.8);font-size:15px;letter-spacing:0}',
    '.chip.foto img{width:100%;height:100%;object-fit:cover;display:block}',
    '.panel{width:min(300px,calc(100vw - 20px));padding:16px;border-radius:14px;border:1px solid rgba(196,181,240,.3);background:#0f1528;',
    '  box-shadow:0 18px 50px rgba(0,0,0,.55);font-size:14px;line-height:1.45}',
    '.titulo{margin:0 0 6px;font:700 18px/1.15 "Barlow Condensed","Barlow",system-ui,sans-serif;letter-spacing:.6px;text-transform:uppercase;color:#fff}',
    '.txt{margin:0 0 12px;color:#c9cedd}',
    '.dato{margin:0;color:#fff;font-weight:600;overflow-wrap:anywhere}',
    '.sub{margin:2px 0 12px;color:#9aa1b5;font-size:13px;overflow-wrap:anywhere}',
    '.btn{width:100%;min-height:40px;padding:0 14px;border-radius:999px;border:0;cursor:pointer;font:600 14px/1 "Barlow Condensed","Barlow",system-ui,sans-serif;',
    '  letter-spacing:1.2px;text-transform:uppercase;display:block}',
    '.btn+.btn{margin-top:8px}',
    '.btn.pri{background:#c4b5f0;color:#0c1122}.btn.pri:hover{background:#d8ccff}',
    '.btn.sec{background:transparent;color:#e8eaf2;border:1px solid rgba(196,181,240,.4)}.btn.sec:hover{border-color:#c4b5f0}',
    '.btn.rojo{background:transparent;color:#ff9c9c;border:1px solid rgba(255,140,140,.4)}.btn.rojo:hover{border-color:#ff9c9c}',
    '.btn[disabled]{opacity:.55;cursor:default}',
    '.pie{margin:12px 0 0;color:#9aa1b5;font-size:12px}',
    '.liga{color:#c4b5f0}',
    '.err{margin:10px 0 0;color:#ff9c9c;font-size:13px}',
    '.msg{width:max-content;max-width:min(300px,calc(100vw - 20px));padding:10px 14px;border-radius:12px;background:#c4b5f0;color:#0c1122;font-size:14px;line-height:1.35;',
    '  box-shadow:0 12px 30px rgba(0,0,0,.45)}'
  ].join('\n');

  function el(tag, attrs, hijos) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'texto') n.textContent = attrs[k];
      else if (k === 'click') n.addEventListener('click', attrs[k]);
      else if (attrs[k] !== null && attrs[k] !== undefined && attrs[k] !== false) n.setAttribute(k, attrs[k] === true ? '' : attrs[k]);
    });
    (hijos || []).forEach(function (h) { if (h) n.appendChild(h); });
    return n;
  }

  function mensaje(t) {
    ui.texto = t;
    clearTimeout(ui.reloj);
    ui.reloj = setTimeout(function () { ui.texto = null; pintar(); }, 7000);
    pintar();
  }

  function montar() {
    if (ui.raiz && ui.raiz.isConnected) return true;
    if (!document.body) return false;
    if (!ui.raiz) {
      ui.raiz = document.createElement('div');
      ui.raiz.id = 'ruleta-cuenta';
      ui.sombra = ui.raiz.attachShadow({ mode: 'open' });
    }
    document.body.insertBefore(ui.raiz, document.body.firstChild);
    return true;
  }

  function accion(fn) {
    return function () {
      if (estado.ocupado) return;
      estado.ocupado = true; ui.error = null; pintar();
      Promise.resolve().then(fn).catch(function (e) {
        console.error(e);
        estado.ocupado = false;
        ui.error = navigator.onLine === false ? 'Sin conexión. Intenta de nuevo.' : 'No se pudo. Intenta de nuevo.';
        pintar();
      });
    };
  }

  function pintar() {
    if (!montar()) return;
    var s = ui.sombra;
    while (s.firstChild) s.removeChild(s.firstChild);
    s.appendChild(el('style', { texto: CSS }));
    var caja = el('div', { class: 'caja' });
    s.appendChild(caja);
    if (!estado.lista) return;                        // hasta saber quién es, no se muestra nada

    var u = estado.usuario;
    var conCuenta = !!(u && !u.is_anonymous);
    var meta = (u && u.user_metadata) || {};
    var nombre = meta.full_name || meta.name || (u && u.email) || 'Tu cuenta';
    var foto = meta.avatar_url || meta.picture || null;

    var alternar = function () { ui.abierto = !ui.abierto; ui.confirmar = false; ui.error = null; pintar(); };
    var chip;
    if (conCuenta) {
      chip = el('button', { class: 'chip foto', type: 'button', 'aria-label': 'Tu cuenta: ' + nombre, 'aria-expanded': String(ui.abierto), click: alternar });
      if (foto) {
        var img = el('img', { src: foto, alt: '', referrerpolicy: 'no-referrer' });
        img.addEventListener('error', function () { chip.textContent = nombre.charAt(0).toUpperCase(); });
        chip.appendChild(img);
      } else {
        chip.textContent = nombre.charAt(0).toUpperCase();
      }
    } else {
      chip = el('button', { class: 'chip', type: 'button', 'aria-expanded': String(ui.abierto), texto: 'Entrar', click: alternar });
    }
    caja.appendChild(chip);

    if (ui.abierto) {
      var panel = el('div', { class: 'panel', role: 'dialog', 'aria-label': conCuenta ? 'Tu cuenta' : 'Entrar' });
      if (!conCuenta) {
        panel.appendChild(el('p', { class: 'titulo', texto: 'Guarda tu progreso' }));
        panel.appendChild(el('p', { class: 'txt', texto: 'Entra con Google para que tus películas calificadas no se pierdan y te sigan en cualquier dispositivo.' }));
        panel.appendChild(el('button', { class: 'btn pri', type: 'button', disabled: estado.ocupado, texto: estado.ocupado ? 'Abriendo Google…' : 'Continuar con Google', click: accion(entrar) }));
        var pie = el('p', { class: 'pie', texto: 'Solo guardamos tu nombre, correo y foto de Google. ' });
        pie.appendChild(el('a', { class: 'liga', href: CONFIG.privacidad, texto: 'Aviso de privacidad' }));
        panel.appendChild(pie);
      } else if (!ui.confirmar) {
        panel.appendChild(el('p', { class: 'dato', texto: nombre }));
        panel.appendChild(el('p', { class: 'sub', texto: (u.email && u.email !== nombre) ? u.email : 'Sesión iniciada con Google' }));
        panel.appendChild(el('button', { class: 'btn sec', type: 'button', disabled: estado.ocupado, texto: 'Cerrar sesión', click: accion(salir) }));
        panel.appendChild(el('button', { class: 'btn rojo', type: 'button', disabled: estado.ocupado, texto: 'Borrar mi cuenta', click: function () { ui.confirmar = true; ui.error = null; pintar(); } }));
        var pie2 = el('p', { class: 'pie' });
        pie2.appendChild(el('a', { class: 'liga', href: CONFIG.privacidad, texto: 'Aviso de privacidad' }));
        panel.appendChild(pie2);
      } else {
        panel.appendChild(el('p', { class: 'titulo', texto: '¿Borrar todo?' }));
        panel.appendChild(el('p', { class: 'txt', texto: 'Se borran tu cuenta y todas las películas que has calificado. No se puede deshacer.' }));
        panel.appendChild(el('button', { class: 'btn rojo', type: 'button', disabled: estado.ocupado, texto: estado.ocupado ? 'Borrando…' : 'Sí, borrar todo', click: accion(borrar) }));
        panel.appendChild(el('button', { class: 'btn sec', type: 'button', disabled: estado.ocupado, texto: 'Cancelar', click: function () { ui.confirmar = false; pintar(); } }));
      }
      if (ui.error) panel.appendChild(el('p', { class: 'err', role: 'alert', texto: ui.error }));
      caja.appendChild(el('div', { class: 'flota' }, [panel]));
    } else if (ui.texto) {
      caja.appendChild(el('div', { class: 'flota' }, [el('div', { class: 'msg', role: 'status', texto: ui.texto })]));
    }
  }

  document.addEventListener('click', function (e) {
    if (ui.abierto && ui.raiz && e.target !== ui.raiz && !estado.ocupado) { ui.abierto = false; ui.confirmar = false; pintar(); }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && ui.abierto && !estado.ocupado) { ui.abierto = false; ui.confirmar = false; pintar(); }
  });
  // Al volver con el botón "atrás" desde Google, la página puede revivir a medias: se rehabilita el botón.
  window.addEventListener('pageshow', function (e) { if (e.persisted) { estado.ocupado = false; pintar(); } });

  function arrancar() {
    pintar();
    asegurarInicio().catch(function (e) { console.warn('cuenta.js: no se pudo iniciar la sesión todavía', e); });
    // Si la pantalla se redibuja y quita el botón, se vuelve a poner
    try {
      new MutationObserver(function () { if (ui.raiz && !ui.raiz.isConnected) pintar(); })
        .observe(document.documentElement, { childList: true, subtree: true });
    } catch (_) {}
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', arrancar);
  else arrancar();
})();
