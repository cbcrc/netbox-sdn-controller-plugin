from django.urls import path
from netbox.views.generic import ObjectChangeLogView
from . import models, views

urlpatterns = (

    # Sdn Controller
    path('sdn-controller/', views.SdnControllerListView.as_view(),
         name='sdncontroller_list'),
    path('sdn-controller/add/', views.SdnControllerEditView.as_view(),
         name='sdncontroller_add'),
    path('sdn-controller/<int:pk>/', views.SdnControllerView.as_view(),
         name='sdncontroller'),
    path('sdn-controller/<int:pk>/imported/', views.ImportedChildrenView.as_view(),
         name='sdncontroller_imported'),
    path('sdn-controller/<int:pk>/discovered/', views.DiscoveredChildrenView.as_view(),
         name='sdncontroller_discovered'),
    path('sdn-controller/<int:pk>/deleted/', views.DeletedChildrenView.as_view(),
         name='sdncontroller_deleted'),
    path('sdn-controller/<int:pk>/inventory/', views.InventoryChildrenView.as_view(),
         name='sdncontroller_inventory'),
    path('sdn-controller/<int:pk>/edit/', views.SdnControllerEditView.as_view(),
         name='sdncontroller_edit'),
    path('sdn-controller/<int:pk>/delete/', views.SdnControllerDeleteView.as_view(),
         name='sdncontroller_delete'),
    path('sdn-controller/<int:pk>/changelog/', ObjectChangeLogView.as_view(),
         name='sdncontroller_changelog',
         kwargs={
             'model': models.SdnController
         }),

    # Sdn Controller Device Prototype
    path('device-prototype/', views.SdnControllerDevicePrototypeListView.as_view(),
         name='sdncontrollerdeviceprototype_list'),
    path('device-prototype/add/', views.SdnControllerDevicePrototypeEditView.as_view(),
         name='sdncontrollerdeviceprototype_add'),
    path('device-prototype/<int:pk>/', views.SdnControllerDevicePrototypeView.as_view(),
         name='sdncontrollerdeviceprototype'),
    path('device-prototype/<int:pk>/edit/', views.SdnControllerDevicePrototypeEditView.as_view(),
         name='sdncontrollerdeviceprototype_edit'),
    path('device-prototype/edit/', views.SdnControllerDevicePrototypeBulkEditView.as_view(),
         name='sdncontrollerdeviceprototype_bulk_edit'),
    path('device-prototype/<int:pk>/delete/', views.SdnControllerDevicePrototypeDeleteView.as_view(),
         name='sdncontrollerdeviceprototype_delete'),
    path('device-prototype/delete/', views.SdnControllerDevicePrototypeBulkDeleteView.as_view(),
         name='sdncontrollerdeviceprototype_bulk_delete'),
    path('device-prototype/<int:pk>/changelog/', ObjectChangeLogView.as_view(),
         name='sdncontrollerdeviceprototype_changelog',
         kwargs={
             'model': models.SdnControllerDevicePrototype
         }),
    path('sdnmodules/add/', views.SdnModuleEditView.as_view(), name='sdnmodule_add'),
    path('sdnmodules/<int:pk>/', views.SdnModuleView.as_view(), name='sdnmodule'),
    path('sdndevices/add/', views.SdnDeviceEditView.as_view(), name='sdndevice_add'),
    path('sdndevices/<int:pk>/', views.SdnDeviceView.as_view(), name='sdndevice'),
    path('launch-task/<int:pk>/', views.launch_task, name='launch_task'),
    path('transfer-to-netbox-task/<int:pk>/', views.transfer_to_netbox_task, name='transfer_to_netbox_task'),
    path('fetch-selected-task/<int:pk>/', views.fetch_selected_task, name='fetch_selected_task'),
    path('sync-prototype/<int:pk>/', views.sync_prototype_task, name='sync_prototype_task'),
    path('fetch-and-sync-prototype/<int:pk>/',
         views.fetch_and_sync_prototype_task,
         name='fetch_and_sync_prototype_task'),
    path('fetch-status/<int:pk>/', views.fetch_status, name='fetch_status'),
)
