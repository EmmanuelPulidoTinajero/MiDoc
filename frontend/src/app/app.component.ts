import { Component, OnDestroy, inject, signal } from '@angular/core';
import { AccesoComponent } from './acceso.component';
import { API_CONFIG_ERROR, AppNotification, ApiService, errorMessage, formatDateTime } from './api.service';
import { BusquedaComponent } from './busqueda.component';
import { CitasComponent } from './citas.component';
import { ExpedienteComponent } from './expediente.component';
import { PanelDoctorComponent } from './panel-doctor.component';
import { MensajesComponent } from './mensajes.component';

type Tab = 'buscar' | 'citas' | 'expediente' | 'panel' | 'mensajes' | 'acceso';

@Component({
  selector: 'midoc-root',
  standalone: true,
  imports: [AccesoComponent, BusquedaComponent, CitasComponent, ExpedienteComponent, PanelDoctorComponent, MensajesComponent],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css'
})
export class AppComponent implements OnDestroy {
  readonly api = inject(ApiService);
  readonly tab = signal<Tab>(this.api.isDoctor() ? 'panel' : 'buscar');
  readonly configError = API_CONFIG_ERROR;
  readonly notifications = signal<AppNotification[]>([]);
  readonly notificationsOpen = signal(false);
  readonly notificationsMessage = signal('');
  readonly formatDateTime = formatDateTime;
  private notificationTimer: number | null = null;
  unreadCount(): number { return this.notifications().filter(item => !item.read).length; }

  reload(): void {
    globalThis.location.reload();
  }

  constructor() {
    if (this.api.user()) {
      void this.api.refreshProfile().catch(() => undefined);
      void this.loadNotifications();
      this.startNotificationPolling();
    }
  }

  signedIn(): void {
    this.navigate(this.api.isDoctor() ? 'panel' : 'buscar');
    void this.loadNotifications();
    this.startNotificationPolling();
  }

  navigate(tab: Tab): void {
    this.tab.set(tab);
    requestAnimationFrame(() => document.getElementById('main-content')?.focus());
  }

  ngOnDestroy(): void {
    if (this.notificationTimer !== null) globalThis.clearInterval(this.notificationTimer);
  }

  logout(): void {
    this.api.logout();
    this.navigate('buscar');
    this.notifications.set([]);
    this.notificationsOpen.set(false);
    if (this.notificationTimer !== null) globalThis.clearInterval(this.notificationTimer);
    this.notificationTimer = null;
  }

  async loadNotifications(): Promise<void> {
    try {
      this.notifications.set(await this.api.get<AppNotification[]>('/api/notifications'));
      this.notificationsMessage.set('');
    } catch (error) {
      this.notificationsMessage.set(errorMessage(error));
    }
  }

  toggleNotifications(): void {
    this.notificationsOpen.update(open => !open);
    if (this.notificationsOpen()) void this.loadNotifications();
  }

  private startNotificationPolling(): void {
    if (this.notificationTimer !== null) globalThis.clearInterval(this.notificationTimer);
    this.notificationTimer = globalThis.setInterval(() => {
      if (this.api.user()) void this.loadNotifications();
      else if (this.notificationTimer !== null) {
        globalThis.clearInterval(this.notificationTimer);
        this.notificationTimer = null;
      }
    }, 15 * 60 * 1000);
  }

  async markNotification(item: AppNotification): Promise<void> {
    if (item.read) return;
    try {
      const updated = await this.api.put<AppNotification>(`/api/notifications/${item.id}/read`, {});
      this.notifications.update(items => items.map(n => n.id === item.id ? updated : n));
    } catch (error) {
      this.notificationsMessage.set(errorMessage(error));
    }
  }
}
