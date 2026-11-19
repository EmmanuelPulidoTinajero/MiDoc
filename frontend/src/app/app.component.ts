import { Component, OnDestroy, effect, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';
import {
  API_CONFIG_ERROR,
  AppNotification,
  ApiService,
  errorMessage,
  formatDateTime,
} from './api.service';
import {
  DsAlertBannerComponent,
  DsBadgeComponent,
  DsButtonComponent,
  DsCardComponent,
  DsEmptyStateComponent,
  DsSkeletonComponent,
} from './ds';

@Component({
  selector: 'midoc-root',
  standalone: true,
  imports: [
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    DsAlertBannerComponent,
    DsBadgeComponent,
    DsButtonComponent,
    DsCardComponent,
    DsEmptyStateComponent,
    DsSkeletonComponent,
  ],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css',
})
export class AppComponent implements OnDestroy {
  readonly api = inject(ApiService);
  private readonly router = inject(Router);
  readonly configError = API_CONFIG_ERROR;
  readonly notifications = signal<AppNotification[]>([]);
  readonly notificationsOpen = signal(false);
  readonly loadingNotifications = signal(false);
  readonly notificationsMessage = signal('');
  readonly formatDateTime = formatDateTime;
  private notificationTimer: ReturnType<typeof globalThis.setInterval> | null = null;
  private lastUserId: string | null = null;
  private navigationCount = 0;

  unreadCount(): number {
    return this.notifications().filter((item) => !item.read).length;
  }

  roleLabel(role: string): string {
    if (role === 'CLINICA') return 'Clínica';
    if (role === 'DOCTOR') return 'Profesional';
    return 'Paciente';
  }

  constructor() {
    this.router.events
      .pipe(
        filter((event): event is NavigationEnd => event instanceof NavigationEnd),
        takeUntilDestroyed(),
      )
      .subscribe(() => {
        this.notificationsOpen.set(false);
        if (this.navigationCount > 0) {
          requestAnimationFrame(() => document.getElementById('main-content')?.focus());
        }
        this.navigationCount += 1;
      });

    effect(() => {
      const user = this.api.user();
      const currentId = user?.id ?? null;
      if (currentId && currentId !== this.lastUserId) {
        this.lastUserId = currentId;
        void this.api.refreshProfile().catch(() => undefined);
        void this.loadNotifications();
        this.startNotificationPolling();
      } else if (!currentId && this.lastUserId !== null) {
        this.lastUserId = null;
        this.notifications.set([]);
        this.notificationsOpen.set(false);
        this.notificationsMessage.set('');
        this.stopNotificationPolling();
      }
    });
  }

  reload(): void {
    globalThis.location.reload();
  }

  focusMain(event: Event): void {
    event.preventDefault();
    document.getElementById('main-content')?.focus();
  }

  ngOnDestroy(): void {
    this.stopNotificationPolling();
  }

  logout(): void {
    this.api.logout();
    this.notifications.set([]);
    this.notificationsOpen.set(false);
    this.stopNotificationPolling();
    void this.router.navigate(['/buscar']);
  }

  async loadNotifications(): Promise<void> {
    if (!this.api.user()) return;
    this.loadingNotifications.set(true);
    try {
      this.notifications.set(await this.api.get<AppNotification[]>('/api/notifications'));
      this.notificationsMessage.set('');
    } catch (error) {
      this.notificationsMessage.set(errorMessage(error));
    } finally {
      this.loadingNotifications.set(false);
    }
  }

  toggleNotifications(): void {
    this.notificationsOpen.update((open) => !open);
    if (this.notificationsOpen()) {
      void this.loadNotifications();
    }
  }

  private startNotificationPolling(): void {
    this.stopNotificationPolling();
    this.notificationTimer = globalThis.setInterval(() => {
      if (this.api.user()) void this.loadNotifications();
      else this.stopNotificationPolling();
    }, 15 * 60 * 1000);
  }

  private stopNotificationPolling(): void {
    if (this.notificationTimer !== null) {
      globalThis.clearInterval(this.notificationTimer);
      this.notificationTimer = null;
    }
  }

  async markNotification(item: AppNotification): Promise<void> {
    if (item.read) return;
    try {
      const updated = await this.api.put<AppNotification>(`/api/notifications/${item.id}/read`, {});
      this.notifications.update((items) => items.map((n) => (n.id === item.id ? updated : n)));
    } catch (error) {
      this.notificationsMessage.set(errorMessage(error));
    }
  }
}
