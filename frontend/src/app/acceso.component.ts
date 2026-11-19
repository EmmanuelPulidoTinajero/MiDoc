import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { ApiService, Role, errorMessage } from './api.service';
import {
  DsAlertBannerComponent,
  DsButtonComponent,
  DsCardComponent,
  DsControlDirective,
  DsFieldComponent,
  DsPageHeaderComponent,
} from './ds';

interface AuthErrors {
  email?: string;
  password?: string;
  name?: string;
  specialty?: string;
  location?: string;
  price?: string;
}

/** Inicio de sesión y registro de pacientes, doctores y clínicas. */
@Component({
  selector: 'midoc-acceso',
  standalone: true,
  imports: [
    FormsModule,
    DsAlertBannerComponent,
    DsButtonComponent,
    DsCardComponent,
    DsControlDirective,
    DsFieldComponent,
    DsPageHeaderComponent,
  ],
  template: `
    <ds-card padding="lg">
      <ds-page-header
        eyebrow="Acceso a tu cuenta"
        [title]="mode() === 'login' ? 'Iniciar sesión' : 'Crear cuenta'"
        subtitle="Accede como paciente o profesional de la salud para gestionar citas, expediente y mensajes."
        [headingLevel]="2"
      />

      <div class="ds-tablist" role="tablist" aria-label="Tipo de acceso">
        <button
          type="button"
          id="tab-login"
          role="tab"
          class="ds-tab"
          [attr.aria-selected]="mode() === 'login'"
          [attr.tabindex]="mode() === 'login' ? 0 : -1"
          aria-controls="panel-auth"
          (click)="setMode('login')"
          (keydown)="onTabKeydown($event, 'login')"
        >
          Iniciar sesión
        </button>
        <button
          type="button"
          id="tab-register"
          role="tab"
          class="ds-tab"
          [attr.aria-selected]="mode() === 'register'"
          [attr.tabindex]="mode() === 'register' ? 0 : -1"
          aria-controls="panel-auth"
          (click)="setMode('register')"
          (keydown)="onTabKeydown($event, 'register')"
        >
          Crear cuenta
        </button>
      </div>

      <div
        id="panel-auth"
        role="tabpanel"
        [attr.aria-labelledby]="mode() === 'login' ? 'tab-login' : 'tab-register'"
        class="stack"
      >
        @if (reasonMessage()) {
          <ds-alert-banner tone="warning" [message]="reasonMessage()" />
        }

        @if (mode() === 'login') {
          <form class="grid-form" (ngSubmit)="login()" novalidate>
            <ds-field label="Correo electrónico" [required]="true" [error]="errors().email ?? ''">
              <input
                dsControl
                type="email"
                name="email"
                [(ngModel)]="email"
                autocomplete="username"
                placeholder="nombre@ejemplo.com"
              />
            </ds-field>
            <ds-field label="Contraseña" [required]="true" [error]="errors().password ?? ''">
              <input
                dsControl
                type="password"
                name="password"
                [(ngModel)]="password"
                autocomplete="current-password"
              />
            </ds-field>
            <div>
              <ds-button type="submit" variant="primary" [loading]="submitting()">
                {{ submitting() ? 'Validando…' : 'Entrar' }}
              </ds-button>
            </div>
          </form>
        } @else {
          <form class="grid-form" (ngSubmit)="register()" novalidate>
            <ds-field label="Tipo de cuenta" [required]="true">
              <select dsControl name="role" [(ngModel)]="role">
                <option value="PACIENTE">Paciente (gratis)</option>
                <option value="DOCTOR">Doctor(a) independiente</option>
                <option value="CLINICA">Consultorio, clínica u hospital</option>
              </select>
            </ds-field>
            <ds-field label="Nombre completo" [required]="true" [error]="errors().name ?? ''">
              <input dsControl name="name" [(ngModel)]="name" autocomplete="name" />
            </ds-field>
            <ds-field label="Correo electrónico" [required]="true" [error]="errors().email ?? ''">
              <input dsControl type="email" name="email" [(ngModel)]="email" autocomplete="username" />
            </ds-field>
            <ds-field
              label="Contraseña"
              hint="Mínimo 8 caracteres, incluyendo letras y números."
              [required]="true"
              [error]="errors().password ?? ''"
            >
              <input dsControl type="password" name="password" [(ngModel)]="password" autocomplete="new-password" />
            </ds-field>
            <ds-field label="Teléfono (opcional)">
              <input dsControl name="phone" [(ngModel)]="phone" autocomplete="tel" />
            </ds-field>
            @if (role !== 'PACIENTE') {
              <ds-field label="Especialidad" [required]="true" [error]="errors().specialty ?? ''">
                <input dsControl name="specialty" [(ngModel)]="specialty" />
              </ds-field>
              <ds-field label="Dirección del consultorio" [required]="true" [error]="errors().location ?? ''">
                <input dsControl name="location" [(ngModel)]="location" />
              </ds-field>
              <ds-field label="Ciudad">
                <input dsControl name="city" [(ngModel)]="city" />
              </ds-field>
              <ds-field label="Precio de consulta (MXN)" [required]="true" [error]="errors().price ?? ''">
                <input dsControl type="number" name="price" min="0" max="100000" [(ngModel)]="price" />
              </ds-field>
            }
            <div class="wide">
              <ds-button type="submit" variant="primary" [loading]="submitting()">
                {{ submitting() ? 'Creando cuenta…' : 'Crear cuenta' }}
              </ds-button>
            </div>
          </form>

          @if (role !== 'PACIENTE') {
            <ds-alert-banner
              tone="info"
              message="Después de registrarte, activa tu suscripción mensual de $20 USD en Mi panel para aparecer en el directorio y publicar tu horario."
            />
          }
        }

        @if (message()) {
          <ds-alert-banner tone="danger" [message]="message()" />
        }
      </div>
    </ds-card>
  `,
})
export class AccesoComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  readonly mode = signal<'login' | 'register'>('login');
  readonly message = signal('');
  readonly reasonMessage = signal('');
  readonly submitting = signal(false);
  readonly errors = signal<AuthErrors>({});
  private returnUrl = '';

  email = '';
  password = '';
  role: Role = 'PACIENTE';
  name = '';
  phone = '';
  specialty = '';
  location = '';
  city = '';
  price = 500;

  ngOnInit(): void {
    const params = this.route.snapshot.queryParamMap;
    const reason = params.get('reason');
    if (reason === 'expired') {
      this.reasonMessage.set('Tu sesión expiró. Inicia sesión nuevamente para continuar.');
    }
    const candidate = params.get('returnUrl') ?? '';
    if (candidate.startsWith('/') && !candidate.startsWith('//')) {
      this.returnUrl = candidate;
    }
  }

  setMode(next: 'login' | 'register'): void {
    this.mode.set(next);
    this.message.set('');
    this.errors.set({});
  }

  onTabKeydown(event: KeyboardEvent, current: 'login' | 'register'): void {
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault();
      const next = current === 'login' ? 'register' : 'login';
      this.setMode(next);
      const targetId = next === 'login' ? 'tab-login' : 'tab-register';
      document.getElementById(targetId)?.focus();
    }
  }

  private validateLogin(): boolean {
    const next: AuthErrors = {};
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(this.email.trim())) {
      next.email = 'Ingresa un correo electrónico válido.';
    }
    if (!this.password.trim()) {
      next.password = 'Ingresa tu contraseña.';
    }
    this.errors.set(next);
    return Object.keys(next).length === 0;
  }

  private validateRegister(): boolean {
    const next: AuthErrors = {};
    if (this.name.trim().length < 2) {
      next.name = 'Ingresa tu nombre completo (mínimo 2 caracteres).';
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(this.email.trim())) {
      next.email = 'Ingresa un correo electrónico válido.';
    }
    if (
      this.password.length < 8 ||
      this.password.length > 128 ||
      !/[a-zA-Z]/.test(this.password) ||
      !/\d/.test(this.password)
    ) {
      next.password = 'Debe tener entre 8 y 128 caracteres con al menos una letra y un número.';
    }
    if (this.role !== 'PACIENTE') {
      if (this.specialty.trim().length < 2) {
        next.specialty = 'Ingresa tu especialidad médica.';
      }
      if (this.location.trim().length < 2) {
        next.location = 'Ingresa la dirección del consultorio.';
      }
      if (!Number.isFinite(Number(this.price)) || Number(this.price) < 0 || Number(this.price) > 100000) {
        next.price = 'Ingresa un precio entre 0 y 100,000 MXN.';
      }
    }
    this.errors.set(next);
    return Object.keys(next).length === 0;
  }

  private async redirectAfterAuth(): Promise<void> {
    if (this.returnUrl && this.returnUrl !== '/acceso') {
      await this.router.navigateByUrl(this.returnUrl);
      return;
    }
    await this.router.navigate([this.api.isDoctor() ? '/panel' : '/buscar']);
  }

  async login(): Promise<void> {
    if (this.submitting()) return;
    this.message.set('');
    if (!this.validateLogin()) return;
    this.submitting.set(true);
    try {
      await this.api.login(this.email.trim(), this.password);
      await this.redirectAfterAuth();
    } catch (error) {
      this.message.set(errorMessage(error));
    } finally {
      this.submitting.set(false);
    }
  }

  async register(): Promise<void> {
    if (this.submitting()) return;
    this.message.set('');
    if (!this.validateRegister()) return;
    this.submitting.set(true);
    const body: Record<string, unknown> = {
      email: this.email.trim(),
      password: this.password,
      role: this.role,
      name: this.name.trim(),
      phone: this.phone.trim() || undefined,
    };
    if (this.role !== 'PACIENTE') {
      Object.assign(body, {
        specialty: this.specialty.trim(),
        location: this.location.trim(),
        city: this.city.trim() || undefined,
        price: Number(this.price),
      });
    }
    try {
      await this.api.register(body);
      await this.redirectAfterAuth();
    } catch (error) {
      this.message.set(errorMessage(error));
    } finally {
      this.submitting.set(false);
    }
  }
}
