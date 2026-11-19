import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import {
  ApiService,
  Appointment,
  ConsultationResult,
  Patient,
  createIdempotencyKey,
  errorMessage,
  formatDateTime,
  formatTime,
  todayInMexico,
} from './api.service';
import {
  DsAlertBannerComponent,
  DsBadgeComponent,
  DsButtonComponent,
  DsCardComponent,
  DsControlDirective,
  DsEmptyStateComponent,
  DsFieldComponent,
  DsModalComponent,
  DsPageHeaderComponent,
  DsSkeletonComponent,
} from './ds';

export type AppointmentFilter = 'TODAS' | 'PENDIENTE' | 'CONFIRMADA' | 'COMPLETADA' | 'CANCELADA';
export type ConsentStatus = 'checking' | 'granted' | 'missing' | 'unknown';

/** Citas del paciente o agenda del profesional, reprogramación y consulta clínica. */
@Component({
  selector: 'midoc-citas',
  standalone: true,
  imports: [
    FormsModule,
    DsAlertBannerComponent,
    DsBadgeComponent,
    DsButtonComponent,
    DsCardComponent,
    DsControlDirective,
    DsEmptyStateComponent,
    DsFieldComponent,
    DsModalComponent,
    DsPageHeaderComponent,
    DsSkeletonComponent,
  ],
  templateUrl: './citas.component.html',
})
export class CitasComponent implements OnInit {
  readonly api = inject(ApiService);
  private readonly router = inject(Router);

  readonly appointments = signal<Appointment[]>([]);
  readonly loading = signal(true);
  readonly loadError = signal('');
  readonly message = signal('');
  readonly messageTone = signal<'info' | 'success' | 'danger'>('info');
  readonly statusFilter = signal<AppointmentFilter>('TODAS');

  readonly attending = signal<Appointment | null>(null);
  readonly patientConsentStatus = signal<ConsentStatus>('unknown');
  readonly lastConsultation = signal<ConsultationResult | null>(null);
  readonly updatingId = signal<string | null>(null);
  readonly savingConsultation = signal(false);

  readonly pendingCancel = signal<Appointment | null>(null);
  readonly canceling = signal(false);

  readonly rescheduling = signal<Appointment | null>(null);
  readonly rescheduleSlots = signal<string[]>([]);
  readonly loadingRescheduleSlots = signal(false);
  readonly rescheduleMessage = signal('');
  readonly savingReschedule = signal(false);

  readonly formatDateTime = formatDateTime;
  readonly formatTime = formatTime;
  readonly minDate = todayInMexico();
  readonly maxDate = todayInMexico(90);

  rescheduleDate = todayInMexico(1);
  selectedSlot = '';
  diagnosis = '';
  treatment = '';
  notes = '';

  readonly filterTabs: Array<{ key: AppointmentFilter; label: string }> = [
    { key: 'TODAS', label: 'Todas' },
    { key: 'PENDIENTE', label: 'Pendientes' },
    { key: 'CONFIRMADA', label: 'Confirmadas' },
    { key: 'COMPLETADA', label: 'Completadas' },
    { key: 'CANCELADA', label: 'Canceladas' },
  ];

  readonly counts = computed(() => {
    const items = this.appointments();
    return {
      TODAS: items.length,
      PENDIENTE: items.filter((a) => a.status === 'PENDIENTE').length,
      CONFIRMADA: items.filter((a) => a.status === 'CONFIRMADA').length,
      COMPLETADA: items.filter((a) => a.status === 'COMPLETADA').length,
      CANCELADA: items.filter((a) => a.status === 'CANCELADA').length,
    };
  });

  readonly filteredAppointments = computed(() => {
    const current = this.statusFilter();
    const items = this.appointments();
    return current === 'TODAS' ? items : items.filter((a) => a.status === current);
  });

  private authorizedPatientIds = new Set<string>();
  private consentCheckUnavailable = false;

  ngOnInit(): void {
    void this.load();
  }

  async load(): Promise<void> {
    this.loading.set(true);
    this.loadError.set('');
    try {
      const list = await this.api.get<Appointment[]>('/api/appointments');
      this.appointments.set(list);
      if (this.api.isDoctor()) {
        await this.refreshAuthorizedPatients();
      }
    } catch (error) {
      this.loadError.set(errorMessage(error));
    } finally {
      this.loading.set(false);
    }
  }

  async refreshAuthorizedPatients(): Promise<void> {
    this.consentCheckUnavailable = false;
    try {
      const patients = await this.api.get<Patient[]>('/api/doctor/patients');
      this.authorizedPatientIds = new Set(patients.map((p) => p.patientId));
    } catch {
      this.authorizedPatientIds = new Set<string>();
      this.consentCheckUnavailable = true;
    }
    const active = this.attending();
    if (active) {
      this.updateConsentSignal(active.patientId);
    }
  }

  private updateConsentSignal(patientId: string): void {
    if (this.consentCheckUnavailable) {
      this.patientConsentStatus.set('unknown');
    } else if (this.authorizedPatientIds.has(patientId)) {
      this.patientConsentStatus.set('granted');
    } else {
      this.patientConsentStatus.set('missing');
    }
  }

  isActive(appointment: Appointment): boolean {
    return appointment.status === 'PENDIENTE' || appointment.status === 'CONFIRMADA';
  }

  canChange(appointment: Appointment): boolean {
    return this.isActive(appointment) && new Date(appointment.dateTime).getTime() > Date.now();
  }

  canAttend(appointment: Appointment): boolean {
    return (
      this.api.isDoctor() &&
      this.isActive(appointment) &&
      new Date(appointment.dateTime).getTime() <= Date.now()
    );
  }

  async attend(appointment: Appointment): Promise<void> {
    this.attending.set(appointment);
    this.diagnosis = '';
    this.treatment = '';
    this.notes = '';
    this.message.set('');
    this.lastConsultation.set(null);
    this.patientConsentStatus.set('checking');
    await this.refreshAuthorizedPatients();
  }

  async beginReschedule(appointment: Appointment): Promise<void> {
    this.rescheduling.set(appointment);
    this.rescheduleDate = todayInMexico(1);
    await this.loadRescheduleSlots();
  }

  closeReschedule(): void {
    if (this.savingReschedule()) return;
    this.rescheduling.set(null);
    this.rescheduleSlots.set([]);
    this.selectedSlot = '';
    this.rescheduleMessage.set('');
  }

  async loadRescheduleSlots(): Promise<void> {
    const appointment = this.rescheduling();
    if (!appointment) return;
    this.rescheduleSlots.set([]);
    this.selectedSlot = '';
    this.loadingRescheduleSlots.set(true);
    this.rescheduleMessage.set('');
    try {
      const result = await this.api.get<{ slots: string[] }>(
        `/api/doctors/${appointment.doctorId}/availability`,
        { date: this.rescheduleDate },
      );
      this.rescheduleSlots.set(result.slots);
      this.rescheduleMessage.set(
        result.slots.length
          ? 'Elige un horario disponible.'
          : 'No hay horarios libres ese día. Prueba otra fecha.',
      );
    } catch (error) {
      this.rescheduleMessage.set(errorMessage(error));
    } finally {
      this.loadingRescheduleSlots.set(false);
    }
  }

  async saveReschedule(): Promise<void> {
    const appointment = this.rescheduling();
    if (!appointment || !this.selectedSlot || this.savingReschedule()) return;
    this.savingReschedule.set(true);
    try {
      await this.api.put(`/api/appointments/${appointment.id}/reschedule`, {
        dateTime: this.selectedSlot,
      });
      this.messageTone.set('success');
      this.message.set('La cita se reprogramó y se envió el aviso correspondiente.');
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
    if (!appointment || this.savingConsultation()) return;
    this.savingConsultation.set(true);
    try {
      const result = await this.api.post<ConsultationResult>(
        '/api/consultations',
        {
          patientId: appointment.patientId,
          appointmentId: appointment.id,
          diagnosis: this.diagnosis.trim(),
          treatment: this.treatment.trim(),
          notes: this.notes.trim() || undefined,
        },
        { 'Idempotency-Key': createIdempotencyKey() },
      );
      this.attending.set(null);
      this.lastConsultation.set(result);
      this.messageTone.set('success');
      this.message.set('Consulta registrada y receta emitida en el historial del paciente.');
      await this.load();
    } catch (error) {
      this.messageTone.set('danger');
      this.message.set(errorMessage(error));
    } finally {
      this.savingConsultation.set(false);
    }
  }

  requestCancel(appointment: Appointment): void {
    this.pendingCancel.set(appointment);
  }

  async confirmCancel(): Promise<void> {
    const appointment = this.pendingCancel();
    if (!appointment || this.canceling()) return;
    this.canceling.set(true);
    this.updatingId.set(appointment.id);
    try {
      await this.api.put(`/api/appointments/${appointment.id}/status`, { status: 'CANCELADA' });
      this.pendingCancel.set(null);
      this.messageTone.set('success');
      this.message.set('La cita se canceló y el horario quedó disponible.');
      await this.load();
    } catch (error) {
      this.pendingCancel.set(null);
      this.messageTone.set('danger');
      this.message.set(`No fue posible cancelar la cita: ${errorMessage(error)}`);
    } finally {
      this.canceling.set(false);
      this.updatingId.set(null);
    }
  }

  async confirmAppointment(appointment: Appointment): Promise<void> {
    this.updatingId.set(appointment.id);
    try {
      await this.api.put(`/api/appointments/${appointment.id}/status`, { status: 'CONFIRMADA' });
      this.messageTone.set('success');
      this.message.set('La cita quedó confirmada.');
      await this.load();
    } catch (error) {
      this.messageTone.set('danger');
      this.message.set(`No fue posible confirmar la cita: ${errorMessage(error)}`);
    } finally {
      this.updatingId.set(null);
    }
  }

  openEmptyCta(): void {
    if (this.statusFilter() !== 'TODAS') {
      this.statusFilter.set('TODAS');
      return;
    }
    void this.router.navigate([this.api.isDoctor() ? '/panel' : '/buscar']);
  }

  onFilterTabKeydown(event: KeyboardEvent, index: number): void {
    const count = this.filterTabs.length;
    let nextIndex: number | null = null;
    if (event.key === 'ArrowRight') {
      nextIndex = (index + 1) % count;
    } else if (event.key === 'ArrowLeft') {
      nextIndex = (index - 1 + count) % count;
    } else if (event.key === 'Home') {
      nextIndex = 0;
    } else if (event.key === 'End') {
      nextIndex = count - 1;
    }
    if (nextIndex === null) return;
    event.preventDefault();
    const nextTab = this.filterTabs[nextIndex];
    this.statusFilter.set(nextTab.key);
    document.getElementById(`citas-tab-${nextTab.key}`)?.focus();
  }

  openPrescriptionDownload(url: string): void {
    globalThis.open(url, '_blank', 'noopener');
  }
}
