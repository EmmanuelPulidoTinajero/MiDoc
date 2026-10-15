import { Component, inject, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService, Role, errorMessage } from './api.service';

/** Inicio de sesión y registro de pacientes, doctores y clínicas. */
@Component({
  selector: 'midoc-acceso',
  standalone: true,
  imports: [FormsModule],
  template: `
    <section class="panel auth">
      <div class="row">
        <button type="button" [class.secondary]="mode() !== 'login'" (click)="mode.set('login')">Iniciar sesión</button>
        <button type="button" [class.secondary]="mode() !== 'register'" (click)="mode.set('register')">Crear cuenta</button>
      </div>

      @if (mode() === 'login') {
        <form class="grid-form" (ngSubmit)="login()">
          <label>Correo <input type="email" name="email" [(ngModel)]="email" required autocomplete="username"></label>
          <label>Contraseña <input type="password" name="password" [(ngModel)]="password" required autocomplete="current-password"></label>
          <button type="submit">Entrar</button>
        </form>
        <p class="muted">Cuentas de demostración: paciente&#64;midoc.local / paciente-demo · doctor&#64;midoc.local / doctor-demo</p>
      } @else {
        <form class="grid-form" (ngSubmit)="register()">
          <label>Tipo de cuenta
            <select name="role" [(ngModel)]="role">
              <option value="PACIENTE">Paciente (gratis)</option>
              <option value="DOCTOR">Doctor(a) independiente</option>
              <option value="CLINICA">Consultorio o clínica</option>
            </select>
          </label>
          <label>Nombre completo <input name="name" [(ngModel)]="name" required></label>
          <label>Correo <input type="email" name="email" [(ngModel)]="email" required autocomplete="username"></label>
          <label>Contraseña (8+ con letras y números)
            <input type="password" name="password" [(ngModel)]="password" required autocomplete="new-password">
          </label>
          <label>Teléfono (opcional) <input name="phone" [(ngModel)]="phone"></label>
          @if (role !== 'PACIENTE') {
            <label>Especialidad <input name="specialty" [(ngModel)]="specialty" required></label>
            <label>Dirección del consultorio <input name="location" [(ngModel)]="location" required></label>
            <label>Ciudad <input name="city" [(ngModel)]="city"></label>
            <label>Precio de consulta (MXN) <input type="number" name="price" min="0" [(ngModel)]="price"></label>
          }
          <button type="submit">Crear cuenta</button>
        </form>
        @if (role !== 'PACIENTE') {
          <p class="muted">Después de registrarte, paga tu suscripción de $20 USD/mes y publica tu horario en "Mi panel".</p>
        }
      }
      @if (message()) { <p role="status" class="notice">{{ message() }}</p> }
    </section>
  `
})
export class AccesoComponent {
  private readonly api = inject(ApiService);
  readonly done = output<void>();
  readonly mode = signal<'login' | 'register'>('login');
  readonly message = signal('');

  email = '';
  password = '';
  role: Role = 'PACIENTE';
  name = '';
  phone = '';
  specialty = '';
  location = '';
  city = '';
  price = 500;

  async login(): Promise<void> {
    try {
      await this.api.login(this.email, this.password);
      this.done.emit();
    } catch (error) {
      this.message.set(errorMessage(error));
    }
  }

  async register(): Promise<void> {
    const body: Record<string, unknown> = {
      email: this.email, password: this.password, role: this.role, name: this.name, phone: this.phone || undefined
    };
    if (this.role !== 'PACIENTE') {
      Object.assign(body, { specialty: this.specialty, location: this.location, city: this.city || undefined, price: this.price });
    }
    try {
      await this.api.register(body);
      this.done.emit();
    } catch (error) {
      this.message.set(errorMessage(error));
    }
  }
}
