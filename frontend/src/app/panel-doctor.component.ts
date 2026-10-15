import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService, DAYS, MedicalRecord, Patient, Profile, Subscription, errorMessage, formatDateTime } from './api.service';
import { ExpedienteVistaComponent } from './expediente-vista.component';

interface BlockForm {
  day: number;
  start: string;
  end: string;
}

/** Flujo 3: suscripción de $20 USD/mes, horario y pacientes autorizados. */
@Component({
  selector: 'midoc-panel-doctor',
  standalone: true,
  imports: [FormsModule, ExpedienteVistaComponent],
  templateUrl: './panel-doctor.component.html'
})
export class PanelDoctorComponent implements OnInit {
  private readonly api = inject(ApiService);
  readonly subscription = signal<Subscription | null>(null);
  readonly patients = signal<Patient[]>([]);
  readonly patientRecord = signal<MedicalRecord | null>(null);
  readonly subscriptionMessage = signal('');
  readonly scheduleMessage = signal('');
  readonly patientsMessage = signal('');
  readonly days = DAYS.map((name, value) => ({ name, value })).slice(1);
  readonly formatDateTime = formatDateTime;

  card = { cardHolder: '', cardNumber: '4242 4242 4242 4242', expMonth: 12, expYear: new Date().getFullYear() + 2, cvv: '123' };
  blocks: BlockForm[] = [];

  ngOnInit(): void {
    void this.load();
  }

  async load(): Promise<void> {
    try {
      const me = await this.api.get<Profile>('/api/me');
      this.subscription.set(me.subscription ?? null);
      const doctor = me.doctor;
      if (doctor) {
        this.blocks = (doctor.schedule ?? []).map(b => ({ day: b.dia_semana, start: b.hora_inicio, end: b.hora_fin }));
        this.card.cardHolder = doctor.name;
      }
      await this.loadPatients();
    } catch (error) {
      this.subscriptionMessage.set(errorMessage(error));
    }
  }

  async loadPatients(): Promise<void> {
    if (!this.subscription()?.active) {
      this.patients.set([]);
      this.patientsMessage.set('Activa tu suscripción para ver a tus pacientes y sus expedientes.');
      return;
    }
    try {
      this.patients.set(await this.api.get<Patient[]>('/api/doctor/patients'));
      this.patientsMessage.set('');
    } catch (error) {
      this.patientsMessage.set(errorMessage(error));
    }
  }

  async pay(): Promise<void> {
    try {
      const result = await this.api.post<Subscription>('/api/subscriptions/pay', this.card);
      this.subscriptionMessage.set(`Pago aprobado con ${result.cardBrand} terminación ${result.cardLast4}. Vigente hasta ${result.end}.`);
      await this.load();
    } catch (error) {
      this.subscriptionMessage.set(errorMessage(error));
    }
  }

  addBlock(): void {
    this.blocks = [...this.blocks, { day: 1, start: '09:00', end: '14:00' }];
  }

  removeBlock(index: number): void {
    this.blocks = this.blocks.filter((_, i) => i !== index);
  }

  async saveSchedule(): Promise<void> {
    try {
      await this.api.put('/api/doctor/schedule', { blocks: this.blocks.map(b => ({ ...b, day: Number(b.day) })) });
      this.scheduleMessage.set('Horario publicado. Los pacientes ya pueden agendar en esos horarios.');
    } catch (error) {
      this.scheduleMessage.set(errorMessage(error));
    }
  }

  async openRecord(patient: Patient): Promise<void> {
    try {
      this.patientRecord.set(await this.api.get<MedicalRecord>('/api/records', { patientId: patient.patientId }));
    } catch (error) {
      this.patientsMessage.set(errorMessage(error));
    }
  }
}
