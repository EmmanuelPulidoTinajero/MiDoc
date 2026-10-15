import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService, Appointment, errorMessage, formatDateTime, todayInMexico } from './api.service';

/** Citas del paciente o agenda del doctor, desde donde registra la consulta. */
@Component({
  selector: 'midoc-citas',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './citas.component.html'
})
export class CitasComponent implements OnInit {
  readonly api = inject(ApiService);
  readonly appointments = signal<Appointment[]>([]);
  readonly message = signal('');
  readonly attending = signal<Appointment | null>(null);
  readonly formatDateTime = formatDateTime;
  diagnosis = '';
  treatment = '';
  notes = '';

  ngOnInit(): void {
    void this.load();
  }

  async load(): Promise<void> {
    try {
      this.appointments.set(await this.api.get<Appointment[]>('/api/appointments'));
    } catch (error) {
      this.message.set(errorMessage(error));
    }
  }

  isActive(appointment: Appointment): boolean {
    return appointment.status === 'PENDIENTE' || appointment.status === 'CONFIRMADA';
  }

  canAttend(appointment: Appointment): boolean {
    const day = new Date(appointment.dateTime).toLocaleDateString('en-CA', { timeZone: 'America/Mexico_City' });
    return this.api.isDoctor() && this.isActive(appointment) && day <= todayInMexico();
  }

  attend(appointment: Appointment): void {
    this.attending.set(appointment);
    this.diagnosis = '';
    this.treatment = '';
    this.notes = '';
    this.message.set('');
  }

  async saveConsultation(): Promise<void> {
    const appointment = this.attending();
    if (!appointment) return;
    try {
      await this.api.post('/api/consultations', {
        patientId: appointment.patientId,
        appointmentId: appointment.id,
        diagnosis: this.diagnosis,
        treatment: this.treatment,
        notes: this.notes || undefined
      });
      this.attending.set(null);
      this.message.set('Consulta registrada; ya aparece en el historial del paciente.');
      await this.load();
    } catch (error) {
      this.message.set(errorMessage(error));
    }
  }
}
