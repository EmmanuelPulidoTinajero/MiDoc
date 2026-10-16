import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService, Appointment, errorMessage, formatDateTime, formatTime, todayInMexico } from './api.service';

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
  readonly updatingId = signal<string | null>(null);
  readonly savingConsultation = signal(false);
  readonly rescheduling = signal<Appointment | null>(null);
  readonly rescheduleSlots = signal<string[]>([]);
  readonly rescheduleMessage = signal('');
  readonly savingReschedule = signal(false);
  readonly formatDateTime = formatDateTime;
  readonly formatTime = formatTime;
  readonly minDate = todayInMexico();
  rescheduleDate = todayInMexico(1);
  selectedSlot = '';
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

  canChange(appointment: Appointment): boolean {
    return this.isActive(appointment) && new Date(appointment.dateTime).getTime() > Date.now();
  }

  canAttend(appointment: Appointment): boolean {
    return this.api.isDoctor() && this.isActive(appointment) && new Date(appointment.dateTime).getTime() <= Date.now();
  }

  attend(appointment: Appointment): void {
    this.attending.set(appointment);
    this.diagnosis = '';
    this.treatment = '';
    this.notes = '';
    this.message.set('');
  }

  async beginReschedule(appointment: Appointment): Promise<void> {
    this.rescheduling.set(appointment);
    this.rescheduleDate = todayInMexico(1);
    await this.loadRescheduleSlots();
  }

  async loadRescheduleSlots(): Promise<void> {
    const appointment = this.rescheduling();
    if (!appointment) return;
    this.rescheduleSlots.set([]);
    this.selectedSlot = '';
    this.rescheduleMessage.set('Consultando disponibilidad…');
    try {
      const result = await this.api.get<{ slots: string[] }>(
        `/api/doctors/${appointment.doctorId}/availability`, { date: this.rescheduleDate }
      );
      this.rescheduleSlots.set(result.slots);
      this.rescheduleMessage.set(result.slots.length ? 'Elige un horario disponible.' : 'No hay horarios libres ese día. Prueba otra fecha.');
    } catch (error) {
      this.rescheduleMessage.set(errorMessage(error));
    }
  }

  async saveReschedule(): Promise<void> {
    const appointment = this.rescheduling();
    if (!appointment || !this.selectedSlot) return;
    this.savingReschedule.set(true);
    try {
      await this.api.put(`/api/appointments/${appointment.id}/reschedule`, { dateTime: this.selectedSlot });
      this.message.set('La cita se reprogramó y se avisó a la otra persona.');
      this.rescheduling.set(null);
      await this.load();
    } catch (error) {
      this.rescheduleMessage.set(errorMessage(error));
    } finally {
      this.savingReschedule.set(false);
    }
  }

  async saveConsultation(): Promise<void> {
    const appointment = this.attending();
    if (!appointment) return;
    this.savingConsultation.set(true);
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
    } finally {
      this.savingConsultation.set(false);
    }
  }

  async changeStatus(appointment: Appointment, status: 'CONFIRMADA' | 'CANCELADA'): Promise<void> {
    const action = status === 'CANCELADA' ? 'cancelar' : 'confirmar';
    if (status === 'CANCELADA' && !globalThis.confirm(`¿Quieres cancelar la cita del ${this.formatDateTime(appointment.dateTime)}?`)) return;
    this.updatingId.set(appointment.id);
    try {
      await this.api.put(`/api/appointments/${appointment.id}/status`, { status });
      this.message.set(status === 'CANCELADA' ? 'La cita se canceló y el horario quedó disponible.' : 'La cita quedó confirmada.');
      await this.load();
    } catch (error) {
      this.message.set(`No fue posible ${action} la cita: ${errorMessage(error)}`);
    } finally {
      this.updatingId.set(null);
    }
  }
}
