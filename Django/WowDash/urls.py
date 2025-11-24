"""
URL configuration for WowDash project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from WowDash import ai_views
from WowDash import authentication_views
from WowDash import blog_views
from WowDash import chart_views
from WowDash import components_views
from WowDash import cryptoCurrency_views
from WowDash import dashboard_views
from WowDash import forms_views
from WowDash import home_views
from WowDash import invoice_views
from WowDash import roleAndAccess_views
from WowDash import settings_views
from WowDash import table_views
from WowDash import users_views
from WowDash import material_views
from WowDash import core_views
from WowDash import optimizer_views
from WowDash import optimizer_autoservicio_clone
from WowDash import operator_views
from WowDash import chat_views
from WowDash import search_views
from WowDash import api_views
from WowDash import configurador_views
from WowDash import operator_views
from WowDash import api_views
from WowDash import autoservicio_views

urlpatterns = [
    # API (mínima)
    path('auth/login', api_views.auth_login, name='api_auth_login'),
    path('api/users', api_views.users_list_api, name='api_users'),
    path('api/users/<int:user_id>/resumen', api_views.user_resumen_api, name='api_user_resumen'),
    path('admin/', admin.site.urls),

# search routes
    path('search/', search_views.global_search, name='global_search'),

# proyectos routes
    path('proyectos/', core_views.proyectos_list, name='proyectos'),
    path('proyectos/agregar/', core_views.add_proyecto, name='add_proyecto'),
    path('proyectos/editar/<int:proyecto_id>/', core_views.edit_proyecto, name='edit_proyecto'),
    path('proyectos/eliminar/<int:proyecto_id>/', core_views.delete_proyecto, name='delete_proyecto'),
    path('proyectos/duplicar/<int:proyecto_id>/', core_views.duplicate_proyecto, name='duplicate_proyecto'),
    path('proyectos/actualizar-estado/', core_views.update_project_status, name='update_project_status'),
    path('proyectos/asignar-operador/', core_views.asignar_operador, name='asignar_operador'),

# clientes routes
    path('clientes/', core_views.clientes_list, name='clientes_lista'),
    path('clientes/agregar/', core_views.add_cliente, name='clientes_agregar'),
    path('clientes/editar/<int:cliente_id>/', core_views.edit_cliente, name='clientes_editar'),
    path('clientes/eliminar/<int:cliente_id>/', core_views.delete_cliente, name='clientes_eliminar'),
    path('api/clientes/buscar/', core_views.buscar_clientes_ajax, name='buscar_clientes_ajax'),

# organizaciones routes
    path('organizaciones/', core_views.organizaciones_list, name='organizaciones_lista'),
    path('organizaciones/agregar/', core_views.add_organizacion, name='organizaciones_agregar'),
    path('organizaciones/<int:organizacion_id>/', core_views.organizacion_detalle, name='organizaciones_detalle'),
    path('organizaciones/editar/<int:organizacion_id>/', core_views.edit_organizacion, name='organizaciones_editar'),
    path('organizaciones/eliminar/<int:organizacion_id>/', core_views.delete_organizacion, name='organizaciones_eliminar'),

# materiales routes
    path('materiales/tableros/', material_views.tableros_list, name='tableros'),
    path('materiales/tableros/agregar/', material_views.add_tablero, name='add_tablero'),
    path('materiales/tableros/editar/<int:tablero_id>/', material_views.edit_tablero, name='edit_tablero'),
    path('materiales/tableros/eliminar/<int:tablero_id>/', material_views.delete_tablero, name='delete_tablero'),
    path('materiales/tableros/search/', material_views.tableros_search_ajax, name='tableros_search_ajax'),
    path('materiales/tableros/importar', material_views.importar_tableros_csv, name='importar_tableros_csv'),
    path('materiales/tableros/plantilla.csv', material_views.descargar_plantilla_tableros, name='descargar_plantilla_tableros'),
    path('materiales/tableros/plantilla_excel.csv', material_views.descargar_plantilla_tableros_excel, name='descargar_plantilla_tableros_excel'),
    path('materiales/tapacantos/', material_views.tapacantos_list, name='tapacantos'),
    path('materiales/tapacantos/agregar/', material_views.add_tapacanto, name='add_tapacanto'),
    path('materiales/tapacantos/editar/<int:tapacanto_id>/', material_views.edit_tapacanto, name='edit_tapacanto'),
    path('materiales/tapacantos/eliminar/<int:tapacanto_id>/', material_views.delete_tapacanto, name='delete_tapacanto'),
    path('materiales/tapacantos/search/', material_views.tapacantos_search_ajax, name='tapacantos_search_ajax'),
    path('materiales/tapacantos/importar', material_views.importar_tapacantos_csv, name='importar_tapacantos_csv'),
    path('materiales/tapacantos/plantilla.csv', material_views.descargar_plantilla_tapacantos, name='descargar_plantilla_tapacantos'),
    path('materiales/tapacantos/plantilla_excel.csv', material_views.descargar_plantilla_tapacantos_excel, name='descargar_plantilla_tapacantos_excel'),

# optimizador routes
    path('optimizador/', optimizer_views.optimizador_home, name='optimizador_home'),  # clásico por defecto
    path('optimizador/nuevo/', optimizer_views.optimizador_home_nuevo, name='optimizador_home_nuevo'),
    path('optimizador/clasico/', optimizer_views.optimizador_home_clasico, name='optimizador_home_clasico'),
    path('optimizador-test/', optimizer_views.optimizador_home_test, name='optimizador_home_test'),  # Temporal sin auth
    path('js-test/', optimizer_views.js_test, name='js_test'),  # Test de JavaScript
    path('optimizador-clean/', optimizer_views.optimizador_clean, name='optimizador_clean'),  # Optimizador limpio
    path('optimizador/crear-proyecto/', optimizer_views.crear_proyecto_optimizacion, name='crear_proyecto_optimizacion'),
    path('optimizador/optimizar/', optimizer_views.optimizar_material, name='optimizar_material'),
    path('optimizador/material-info/<int:material_id>/', optimizer_views.obtener_material_info, name='obtener_material_info'),
    path('optimizador/exportar-entrada/<int:proyecto_id>/', optimizer_views.exportar_json_entrada, name='exportar_json_entrada'),
    path('optimizador/exportar-salida/<int:proyecto_id>/', optimizer_views.exportar_json_salida, name='exportar_json_salida'),
        path('optimizador/forzar-optimizacion/<int:proyecto_id>/', optimizer_views.forzar_optimizacion, name='forzar_optimizacion'),
    # Ruta legacy exportar_pdf eliminada (usar exportar_pdf_snapshot / exportar_pdf_snapshot_cached)
    # Nuevas rutas PDF rápidas (snapshot HTML)
    path('optimizador/exportar-pdf-snapshot/<int:proyecto_id>/', optimizer_views.exportar_pdf_snapshot, name='exportar_pdf_snapshot'),
    path('optimizador/exportar-pdf-snapshot-cached/<int:proyecto_id>/', optimizer_views.exportar_pdf_snapshot_cached, name='exportar_pdf_snapshot_cached'),
    path('optimizador/exportar-pdf-json/<int:proyecto_id>/', optimizer_views.exportar_pdf_json, name='exportar_pdf_json'),
    # Ruta legacy reintroducida para compatibilidad (algunas plantillas aún usan reverse('exportar_pdf'))
    # Delegamos al método antiguo por ahora; se puede redirigir a snapshot/json más adelante.
    path('optimizador/exportar-pdf/<int:proyecto_id>/', optimizer_views.exportar_pdf, name='exportar_pdf'),
    path('optimizador/guardar-layout-manual/', optimizer_views.guardar_layout_manual, name='guardar_layout_manual'),
    path('optimizador/proyectos/', optimizer_views.proyectos_optimizador, name='proyectos_optimizador'),
    path('optimizador/abrir/<int:proyecto_id>/', optimizer_views.optimizador_abrir, name='optimizador_abrir'),
    path('optimizador/proyectos/preview-json/<int:proyecto_id>/', optimizer_views.preview_proyecto_json, name='preview_proyecto_json'),
    # Optimizador autoservicio clon independiente
    path('optimizador_autoservicio/', optimizer_autoservicio_clone.optimizador_autoservicio_home_clone, name='optimizador_autoservicio_home_clone'),
    path('optimizador_autoservicio/crear-proyecto/', optimizer_autoservicio_clone.crear_proyecto_optimizacion_clone, name='crear_proyecto_optimizacion_clone'),
    path('optimizador_autoservicio/optimizar/', optimizer_autoservicio_clone.optimizar_material_clone, name='optimizar_material_clone'),
    path('optimizador_autoservicio/exportar-entrada/<int:proyecto_id>/', optimizer_autoservicio_clone.exportar_json_entrada_clone, name='exportar_json_entrada_clone'),
    path('optimizador_autoservicio/exportar-salida/<int:proyecto_id>/', optimizer_autoservicio_clone.exportar_json_salida_clone, name='exportar_json_salida_clone'),
    path('optimizador_autoservicio/exportar-pdf/<int:proyecto_id>/', optimizer_autoservicio_clone.exportar_pdf_clone, name='exportar_pdf_clone'),
    
    # AJAX endpoints para clientes
    # Nota: Evitar colisión de nombre con la API general en core_views
    path('optimizador/buscar-clientes/', optimizer_views.buscar_clientes_ajax, name='opt_buscar_clientes_ajax'),
    path('optimizador/crear-cliente/', optimizer_views.crear_cliente_ajax, name='crear_cliente_ajax'),
    
    # Rutas de autoservicio
    path('autoservicio/', autoservicio_views.autoservicio_landing, name='autoservicio_landing'),
    path('autoservicio/hub/', autoservicio_views.autoservicio_hub, name='autoservicio_hub'),
    path('autoservicio/mis-proyectos/', autoservicio_views.autoservicio_mis_proyectos, name='autoservicio_mis_proyectos'),
    path('autoservicio/finalizar/<int:proyecto_id>/', autoservicio_views.autoservicio_finalizar_proyecto, name='autoservicio_finalizar_proyecto'),
    path('autoservicio/api/buscar-rut/', autoservicio_views.autoservicio_buscar_rut, name='autoservicio_buscar_rut'),
    path('autoservicio/api/crear-cliente/', autoservicio_views.autoservicio_crear_cliente, name='autoservicio_crear_cliente'),
    path('autoservicio/logout-cliente/', autoservicio_views.autoservicio_logout_cliente, name='autoservicio_logout_cliente'),
    path('autoservicio/optimizador/', optimizer_views.optimizador_autoservicio, name='optimizador_autoservicio'),
    path('autoservicio/portada-pdf/<int:proyecto_id>/', optimizer_views.autoservicio_portada_pdf, name='autoservicio_portada_pdf'),

# operador routes
    path('operador/', operator_views.operador_home, name='operador_home'),
    path('operador/historial/', operator_views.operador_historial, name='operador_historial'),
    path('operador/proyecto/<int:proyecto_id>/', operator_views.operador_proyecto, name='operador_proyecto'),
    path('operador/corte-guiado/<int:proyecto_id>/', operator_views.operador_corte_guiado, name='operador_corte_guiado'),

# chat routes (real functionality)
    path('chat/', chat_views.chat_lista, name='chat'),
    path('chat/conversacion/<int:conversacion_id>/', chat_views.chat_conversacion, name='chat_conversacion'),
    path('chat/enviar-mensaje/', chat_views.enviar_mensaje, name='enviar_mensaje'),
    path('chat/crear-conversacion/', chat_views.crear_conversacion, name='crear_conversacion'),
    path('chat/obtener-mensajes/<int:conversacion_id>/', chat_views.obtener_mensajes, name='obtener_mensajes'),
    path('chat/buscar-mensajes/', chat_views.buscar_mensajes, name='buscar_mensajes'),
    path('chat/perfil/<int:user_id>/', chat_views.chat_perfil, name='chat_perfil'),
    path('chat/buscar-usuarios/', chat_views.buscar_usuarios, name='buscar_usuarios'),
    path('chat/unread-summary/', chat_views.unread_summary, name='chat_unread_summary'),

# api minimal
    path('api/auth/login', api_views.auth_login, name='api_auth_login'),
    path('api/users', api_views.users_list_api, name='api_users_list'),
    path('api/users/<int:user_id>/resumen', api_views.user_resumen_api, name='api_user_resumen'),
    path('api/analytics/optimizations', api_views.analytics_optimizations, name='api_analytics_optimizations'),
    # operador APIs
    path('api/operador/proyectos', api_views.operador_proyectos_api, name='api_operador_proyectos'),
    path('api/operador/proyectos/<int:proyecto_id>', api_views.operador_proyecto_detalle_api, name='api_operador_proyecto_detalle'),
    path('api/operador/proyectos/<int:proyecto_id>/estado', api_views.operador_proyecto_estado_api, name='api_operador_proyecto_estado'),
    path('api/operador/proyectos/<int:proyecto_id>/piezas/marcar-todas', api_views.operador_proyecto_marcar_todas_cortadas_api, name='api_operador_proyecto_marcar_todas'),
    path('api/operador/proyectos/<int:proyecto_id>/piezas/<str:pieza_id>', api_views.operador_pieza_estado_api, name='api_operador_pieza_estado'),
    path('api/operador/proyectos/<int:proyecto_id>/completar', api_views.operador_proyecto_completar_api, name='api_operador_proyecto_completar'),

# home routes

    path('', home_views.index),
    path('index', home_views.index, name='index'),
    path('blankpage', home_views.blankpage, name='blankpage'),
    path('calendar', home_views.calendar, name='calendar'),
    path('chat-profile', home_views.chatProfile, name='chatProfile'),
    path('comingsoon', home_views.comingsoon, name='comingsoon'),
    path('email', home_views.email, name='email'),
    path('faqs', home_views.faqs, name='faqs'),
    path('gallery', home_views.gallery, name='gallery'),
    path('kanban', home_views.kanban, name='kanban'),
    path('maintenance', home_views.maintenance, name='maintenance'),
    path('not-found', home_views.notFound, name='notFound'),
    path('pricing', home_views.pricing, name='pricing'),
    path('stared', home_views.stared, name='stared'),
    path('terms-conditions', home_views.termsAndConditions, name='termsAndConditions'),
    path('testimonials', home_views.testimonials, name='testimonials'),
    path('view-details', home_views.viewDetails, name='viewDetails'),
    path('widgets', home_views.widgets, name='widgets'),
    path('public', home_views.public, name='public'),
    # operador web
    path('operador/', operator_views.operador_home, name='operador_home'),
    path('operador/historial/', operator_views.operador_historial, name='operador_historial'),
    path('operador/proyecto/<int:proyecto_id>/', operator_views.operador_proyecto, name='operador_proyecto'),

# ai routes
    path('ai/code-generator', ai_views.codeGenerator, name='codeGenerator'),
    path('ai/code-generatorNew', ai_views.codeGeneratorNew, name='codeGeneratorNew'),
    path('ai/image-generator', ai_views.imageGenerator, name='imageGenerator'),
    path('ai/text-generator', ai_views.textGenerator, name='textGenerator'),
    path('ai/text-generator-new', ai_views.textGeneratorNew, name='textGeneratorNew'),
    path('ai/video-generator', ai_views.videoGenerator, name='videoGenerator'),
    path('ai/voice-generator', ai_views.voiceGenerator, name='voiceGenerator'),


# authentication routes
    path('authentication/signin/', authentication_views.signin, name='signin'),
    path('authentication/password-change/', authentication_views.password_change_view, name='password_change'),
    path('authentication/signup/', authentication_views.signup, name='signup'),
    path('authentication/forgot-password/', authentication_views.forgotPassword, name='forgotPassword'),
    path('login/', auth_views.LoginView.as_view(template_name='authentication/signin.html'), name='login'),
    path('logout/', authentication_views.signout, name='logout'),
    path('accounts/login/', auth_views.LoginView.as_view(template_name='authentication/signin.html'), name='accounts_login'),

# herramientas / super admin
    path('herramientas/configurador-3d/', configurador_views.configurador_3d, name='configurador_3d'),
    path('herramientas/configurador-3d/materiales-json/', configurador_views.materiales_json, name='config3d_materiales_json'),
    path('herramientas/configurador-3d/tapacantos-json/', configurador_views.tapacantos_json, name='config3d_tapacantos_json'),
    path('herramientas/configurador-3d/autosave/', configurador_views.configurador_autosave, name='config3d_autosave'),
    path('herramientas/configurador-3d/exportar-pdf/<int:proyecto_id>/', configurador_views.configurador_pdf, name='config3d_exportar_pdf'),

# blog routes
    path('blog/add-blog', blog_views.addBlog, name='addBlog'),
    path('blog/blog', blog_views.blog, name='blog'),
    path('blog/blog-details', blog_views.blogDetails, name='blogDetails'),

# chart routes
    path('chart/column-chart', chart_views.columnChart, name='columnChart'),
    path('chart/line-chart', chart_views.lineChart, name='lineChart'),
    path('chart/pie-chart', chart_views.pieChart, name='pieChart'),

# components routes
    path('components/alerts', components_views.alerts, name='alerts'),
    path('components/avatars', components_views.avatars, name='avatars'),
    path('components/badges', components_views.badges, name='badges'),
    path('components/button', components_views.button, name='button'),
    path('components/calendar', components_views.calendar, name='calendarMain'),
    path('components/card', components_views.card, name='card'),
    path('components/carousel', components_views.carousel, name='carousel'),
    path('components/colors', components_views.colors, name='colors'),
    path('components/dropdown', components_views.dropdown, name='dropdown'),
    path('components/list', components_views.list, name='list'),
    path('components/pagination', components_views.pagination, name='pagination'),
    path('components/progressbar', components_views.progressbar, name='progressbar'),
    path('components/radio', components_views.radio, name='radio'),
    path('components/star-ratings', components_views.starRatings, name='starRatings'),
    path('components/switch', components_views.switch, name='switch'),
    path('components/tab-accordion', components_views.tabAndAccordion, name='tabAndAccordion'),
    path('components/tags', components_views.tags, name='tags'),
    path('components/tooltip', components_views.tooltip, name='tooltip'),
    path('components/typography', components_views.typography, name='typography'),
    path('components/upload', components_views.upload, name='upload'),
    path('components/videos', components_views.videos, name='videos'),

# cryptoCurrency routes

    path('crypto-currency/marketplace', cryptoCurrency_views.marketplace, name='marketplace'),
    path('crypto-currency/marketplace-details', cryptoCurrency_views.marketplaceDetails, name='marketplaceDetails'),
    path('crypto-currency/portfolio', cryptoCurrency_views.portfolio, name='portfolio'),
    path('crypto-currency/wallet', cryptoCurrency_views.wallet, name='wallet'),

# dashboard routes

    path('dashboard/index2', dashboard_views.index2, name="index2"),
    path('dashboard/index3', dashboard_views.index3, name="index3"),
    path('dashboard/index4', dashboard_views.index4, name="index4"),
    path('dashboard/index5', dashboard_views.index5, name="index5"),
    path('dashboard/index6', dashboard_views.index6, name="index6"),
    path('dashboard/index7', dashboard_views.index7, name="index7"),
    path('dashboard/index8', dashboard_views.index8, name="index8"),
    path('dashboard/index9', dashboard_views.index9, name="index9"),
    path('dashboard/index10', dashboard_views.index10, name="index10"),


# forms routes

    path('forms/form-validation', forms_views.formValidation, name="formValidation"),
    path('forms/form-wizard', forms_views.formWizard, name="formWizard"),
    path('forms/input-forms', forms_views.inputForms, name="inputForms"),
    path('forms/input-layout', forms_views.inputLayout, name="inputLayout"),

# invoices routes

    path('invoice/add-new', invoice_views.addNew, name='addNew'),
    path('invoice/edit', invoice_views.edit, name='edit'),
    path('invoice/list', invoice_views.list, name='invoiceList'),
    path('invoice/preview', invoice_views.preview, name='preview'),

    # role and access routes

    path('role-access/assign-role', roleAndAccess_views.assignRole, name='assignRole'),
    path('role-access/role-access', roleAndAccess_views.roleAccess, name='roleAccess'),

#settings routes

    path('settings/company', settings_views.company, name='company'),
    path('settings/currencies', settings_views.currencies, name='currencies'),
    path('settings/languages', settings_views.languages, name='languages'),
    path('settings/notification', settings_views.notification, name='notification'),
    path('settings/notification-alert', settings_views.notificationAlert, name='notificationAlert'),
    path('settings/payment-getway', settings_views.paymentGetway, name='paymentGetway'),
    path('settings/theme', settings_views.theme, name='theme'),

# tables routes

    path('tables/basic-table', table_views.basicTable, name='basicTable'),
    path('tables/data-table', table_views.dataTable, name='dataTable'),

#users routes

    path('users/add-user/', users_views.addUser, name='addUser'),
    path('users/edit-user/<int:user_id>/', users_views.editUser, name='editUser'),
    path('users/edit-profile/', users_views.edit_own_profile, name='editOwnProfile'),
    path('users/delete-user/<int:user_id>/', users_views.delete_user, name='delete_user'),
    path('users/users-grid/', users_views.usersGrid, name='usersGrid'),
    path('users/users-list/', users_views.usersList, name='usersList'),
    path('users/view-profile/', users_views.viewProfile, name='viewProfile'),
    path('users/support-report/', users_views.support_users_report, name='supportUsersReport'),
    path('users/force-password-change/<int:user_id>/', users_views.force_password_change, name='forcePasswordChange'),
    path('users/bulk-delete-others/', users_views.bulk_delete_other_users, name='bulkDeleteOthers'),

]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

