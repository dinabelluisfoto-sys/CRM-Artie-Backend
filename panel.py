import flet as ft
import requests

# CONFIGURACIÓN - Tu link de Railway
URL_BASE = "https://crm-artie-backend-production.up.railway.app"

def main(page: ft.Page):
    # Configuración de la Ventana
    page.title = "CRM La Sanjuanerita - Mesa de Control"
    page.bgcolor = "#F8F9FA" # Gris muy claro de fondo
    page.theme_mode = "light"
    page.padding = 0 # Importante para que el Sidebar pegue al borde
    page.window_width = 1100
    page.window_height = 700

    # --- VARIABLES DE ESTADO ---
    pedido_seleccionado = ft.Column(expand=True, spacing=20)

    # --- COMPONENTES VISUALES ---
    lista_leads = ft.Column(scroll="auto", spacing=5)

    def cargar_sidebar(e=None):
        lista_leads.controls.clear()
        try:
            # Agregamos un timeout de 5 segundos para evitar que la app se congele si la API no responde
            resp = requests.get(f"{URL_BASE}/api/dashboard/", timeout=5)
            if resp.status_code == 200:
                for p in resp.json():
                    color_dot = "green" if not p['bot_activo'] else "orange"
                    
                    lista_leads.controls.append(
                        ft.Container(
                            content=ft.Row([
                                ft.CircleAvatar(
                                    content=ft.Text(p['cliente_nombre'][0].upper()),
                                    bgcolor="bluegrey100"
                                ),
                                ft.Column([
                                    ft.Text(p['cliente_nombre'], size=14, weight="bold"),
                                    ft.Text(f"Q{p['total_q']} - {p['cantidad']} gorras", size=12, color="grey"),
                                ], spacing=2, expand=True),
                                ft.Container(width=10, height=10, bgcolor=color_dot, border_radius=5)
                            ]),
                            padding=15,
                            border_radius=10,
                            on_click=lambda e, data=p: ver_detalle(data),
                            # Usamos un string simple para el hover para evitar caídas por versión
                            hover_style=ft.ButtonStyle(bgcolor="#F0F2F5") 
                        )
                    )
            page.update()
        except Exception as ex:
            print(f"Error cargando sidebar: {ex}")

    def ver_detalle(datos):
        pedido_seleccionado.controls.clear()
        
        pedido_seleccionado.controls.append(
            ft.Container(
                padding=30,
                content=ft.Column([
                    ft.Row([
                        ft.Text(datos['cliente_nombre'], size=30, weight="bold"), # Cambiado "w900" por "bold"
                        ft.Container(
                            padding=10, bgcolor="blue", border_radius=10,
                            content=ft.Text(datos['estatus'], color="white", weight="bold")
                        )
                    ], alignment="spaceBetween"),
                    ft.Divider(height=40),
                    ft.Text("DATOS DE CONTACTO", size=12, weight="bold", color="grey"),
                    ft.Text(f"📞 Teléfono: +502 {datos['telefono']}", size=18),
                    ft.Text(f"📝 NIT: {datos['nit']}", size=18),
                    ft.Divider(height=40),
                    ft.Text("DETALLES DEL PEDIDO", size=12, weight="bold", color="grey"),
                    ft.Row([
                        ft.Icon("store"),
                        ft.Text(f"Cantidad: {datos['cantidad']} Unidades", size=18),
                    ]),
                    ft.Text(f"Inversión Total: Q{datos['total_q']}", size=24, color="green", weight="bold"),
                    ft.Container(height=20),
                    ft.ElevatedButton(
                        text="DETENER ARTIE (Modo Humano)" if datos['bot_activo'] else "ENCENDER ARTIE (Modo Bot)",
                        bgcolor="red" if datos['bot_activo'] else "green",
                        color="white",
                        height=50,
                        on_click=lambda e: toggle_bot_server(datos['telefono'])
                    )
                ])
            )
        )
        page.update()

    def toggle_bot_server(tel):
        try:
            requests.post(f"{URL_BASE}/api/toggle_bot/{tel}", timeout=5)
            cargar_sidebar() 
            pedido_seleccionado.controls.clear()
            pedido_seleccionado.controls.append(ft.Text("Actualizando estado...", italic=True))
            page.update()
        except Exception as ex:
            print(f"Error en toggle: {ex}")

    # --- LAYOUT PRINCIPAL (SPA) ---
    sidebar = ft.Container(
        width=350,
        bgcolor="white",
        padding=20,
        content=ft.Column([
            ft.Row([
                ft.Text("SANJUANERITA", size=20, weight="bold", color="bluegrey"), # Cambiado "w900" por "bold"
                ft.IconButton(icon="refresh", on_click=cargar_sidebar)
            ], alignment="spaceBetween"),
            # SOLUCIÓN AL ERROR: Cambiado 'placeholder' por 'hint_text' que es universal en Flet
            ft.TextField(prefix_icon="search", hint_text="Buscar cliente...", border_radius=20, text_size=12),
            ft.Divider(),
            lista_leads
        ])
    )

    main_content = ft.Container(
        expand=True,
        bgcolor="#F0F2F5",
        content=pedido_seleccionado
    )

    page.add(
        ft.Row([
            sidebar,
            main_content
        ], expand=True, spacing=0)
    )

    cargar_sidebar()

ft.app(target=main)