import { Component, inject, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService, DAYS, Doctor, errorMessage, formatTime, todayInMexico } from './api.service';

/** Flujo 1: buscar profesionales, ver perfil y horarios libres, y agendar. */
@Component({
  selector: 'midoc-busqueda',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './busqueda.component.html'
})
export class BusquedaComponent {
  readonly api = inject(ApiService);
  readonly booked = output<void>();
  readonly loginRequested = output<void>();

  specialty = '';
  location = '';
  text = '';
  readonly doctors = signal<Doctor[]>([]);
  readonly searching = signal(false);
  readonly searched = signal(false);
  readonly booking = signal(false);
  readonly openingDoctor = signal(false);
  readonly updatingConsent = signal(false);
  readonly message = signal('Busca un profesional para comenzar.');

  readonly selected = signal<Doctor | null>(null);
  date = todayInMexico(1);
  readonly slots = signal<string[]>([]);
  readonly slotsMessage = signal('');
  reason = '';
  readonly bookingMessage = signal('');
  readonly minDate = todayInMexico();
  readonly days = DAYS;
  readonly formatTime = formatTime;

  async search(): Promise<void> {
    const params: Record<string, string> = {};
    if (this.specialty.trim()) params['specialty'] = this.specialty.trim();
    if (this.location.trim()) params['location'] = this.location.trim();
    if (this.text.trim()) params['q'] = this.text.trim();
    this.searching.set(true);
    this.searched.set(true);
    try {
      const result = await this.api.get<Doctor[]>('/api/doctors', params);
      this.doctors.set(result);
      this.message.set(`${result.length} profesional(es) encontrado(s).`);
    } catch (error) {
      this.message.set(`No fue posible consultar la API: ${errorMessage(error)}`);
    } finally {
      this.searching.set(false);
    }
  }

  async open(doctor: Doctor): Promise<void> {
    this.bookingMessage.set('');
    this.openingDoctor.set(true);
    try {
      this.selected.set(await this.api.get<Doctor>(`/api/doctors/${doctor.id}`));
      await this.loadSlots();
    } catch (error) {
      this.message.set(errorMessage(error));
    } finally {
      this.openingDoctor.set(false);
    }
  }

  async loadSlots(): Promise<void> {
    const doctor = this.selected();
    if (!doctor) return;
    this.slotsMessage.set('Consultando horarios...');
    try {
      const result = await this.api.get<{ slots: string[] }>(`/api/doctors/${doctor.id}/availability`, { date: this.date });
      this.slots.set(result.slots);
      this.slotsMessage.set(result.slots.length ? '' : 'No hay horarios libres ese día. Prueba otra fecha.');
    } catch (error) {
      this.slots.set([]);
      this.slotsMessage.set(errorMessage(error));
    }
  }

  async book(slot: string): Promise<void> {
    if (this.booking()) return;
    const doctor = this.selected();
    if (!doctor) return;
    if (!this.api.isPatient()) {
      this.bookingMessage.set('Inicia sesión como paciente para agendar.');
      this.loginRequested.emit();
      return;
    }
    this.booking.set(true);
    try {
      await this.api.post('/api/appointments', { doctorId: doctor.id, dateTime: slot, reason: this.reason || undefined });
      this.bookingMessage.set(`Cita agendada con ${doctor.name} a las ${formatTime(slot)}. Puedes verla en "Mis citas".`);
      this.reason = '';
      await this.loadSlots();
      this.booked.emit();
    } catch (error) {
      this.bookingMessage.set(errorMessage(error));
      await this.loadSlots();
    } finally {
      this.booking.set(false);
    }
  }

  async grantAccess(): Promise<void> {
    const doctor = this.selected();
    if (!doctor || this.updatingConsent()) return;
    this.updatingConsent.set(true);
    try {
      await this.api.post('/api/consents', { doctorId: doctor.id, granted: true });
      this.bookingMessage.set(`${doctor.name} ya puede consultar tu expediente. Puedes revocarlo en "Mi expediente".`);
    } catch (error) {
      this.bookingMessage.set(errorMessage(error));
    } finally {
      this.updatingConsent.set(false);
    }
  }
}
