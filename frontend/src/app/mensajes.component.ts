import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService, Appointment, Consent, Doctor, Patient, errorMessage, formatDateTime } from './api.service';

interface Conversation {
  userId: string;
  name: string;
  lastMessage: string;
  updatedAt: string;
  unread: number;
}

interface Message {
  id: string;
  senderId: string;
  recipientId: string;
  content: string;
  createdAt: string;
  read: boolean;
}

/** Mensajes protegidos entre paciente y profesional con relación previa. */
@Component({
  selector: 'midoc-mensajes',
  standalone: true,
  imports: [FormsModule],
  template: `
    <section class="panel" aria-labelledby="messages-title">
      <h2 id="messages-title">Mensajes privados</h2>
      <p class="muted">Puedes escribir a profesionales con quienes tienes una cita o consentimiento activo. No uses este canal para emergencias.</p>
      <div class="grid-form">
        <label>Conversación
          <select name="conversation" [(ngModel)]="otherUserId" (change)="loadConversation()">
            <option value="">Elige una persona</option>
            @for (contact of contacts(); track contact.userId) {
              <option [value]="contact.userId">{{ contact.name }}{{ contact.unread ? ' · ' + contact.unread + ' sin leer' : '' }}</option>
            }
          </select>
        </label>
        <button type="button" class="secondary" (click)="load()">Actualizar conversaciones</button>
      </div>
      @if (message()) { <p role="status" aria-live="polite">{{ message() }}</p> }
      @if (otherUserId) {
        <ol class="message-list" aria-label="Mensajes de esta conversación" aria-live="polite">
          @for (item of messages(); track item.id) {
            <li [class.own-message]="item.senderId === api.user()?.id">
              <p>{{ item.content }}</p>
              <time>{{ item.senderId === api.user()?.id ? 'Tú · ' : '' }}{{ formatDateTime(item.createdAt) }}</time>
            </li>
          } @empty { <li>Aún no hay mensajes. Puedes iniciar la conversación.</li> }
        </ol>
        <form class="stack" (ngSubmit)="send()">
          <label>Escribe tu mensaje
            <textarea name="content" [(ngModel)]="content" maxlength="2000" required rows="3" [disabled]="sending()"></textarea>
          </label>
          <button type="submit" [disabled]="sending() || !content.trim()">{{ sending() ? 'Enviando…' : 'Enviar mensaje' }}</button>
        </form>
      } @else {
        <p class="muted">{{ contacts().length ? 'Selecciona una conversación para verla.' : 'Las conversaciones aparecerán después de una cita o de otorgar consentimiento.' }}</p>
      }
    </section>
  `
})
export class MensajesComponent implements OnInit {
  readonly api = inject(ApiService);
  readonly contacts = signal<Conversation[]>([]);
  readonly messages = signal<Message[]>([]);
  readonly message = signal('');
  readonly sending = signal(false);
  readonly formatDateTime = formatDateTime;
  otherUserId = '';
  content = '';

  ngOnInit(): void { void this.load(); }

  async load(): Promise<void> {
    try {
      const threads = await this.api.get<Conversation[]>('/api/messages');
      const known = new Map(threads.map(thread => [thread.userId, thread]));
      if (this.api.isDoctor()) {
        const patients = await this.api.get<Patient[]>('/api/doctor/patients');
        for (const patient of patients) known.set(patient.patientId, known.get(patient.patientId) ?? {
          userId: patient.patientId, name: patient.name || patient.email, lastMessage: '', updatedAt: patient.accessSince, unread: 0
        });
      } else {
        const [doctors, consents, appointments] = await Promise.all([
          this.api.get<Doctor[]>('/api/doctors'), this.api.get<Consent[]>('/api/consents'), this.api.get<Appointment[]>('/api/appointments')
        ]);
        const permitted = new Set(consents.filter(item => item.granted).map(item => item.doctorId));
        const booked = new Set(appointments.map(item => item.doctorId));
        for (const doctor of doctors) {
          if ((permitted.has(doctor.id) || booked.has(doctor.id)) && doctor.userId) {
            known.set(doctor.userId, known.get(doctor.userId) ?? {
              userId: doctor.userId, name: doctor.name, lastMessage: '', updatedAt: '', unread: 0
            });
          }
        }
      }
      this.contacts.set([...known.values()].sort((a, b) => (b.updatedAt || '').localeCompare(a.updatedAt || '')));
      if (this.otherUserId && this.contacts().some(contact => contact.userId === this.otherUserId)) await this.loadConversation();
      this.message.set('');
    } catch (error) {
      this.message.set(errorMessage(error));
    }
  }

  async loadConversation(): Promise<void> {
    if (!this.otherUserId) { this.messages.set([]); return; }
    try {
      this.messages.set(await this.api.get<Message[]>(`/api/messages/${this.otherUserId}`));
      this.contacts.update(items => items.map(item => item.userId === this.otherUserId ? { ...item, unread: 0 } : item));
      this.message.set('');
    } catch (error) {
      this.messages.set([]);
      this.message.set(errorMessage(error));
    }
  }

  async send(): Promise<void> {
    const content = this.content.trim();
    if (!content || !this.otherUserId || this.sending()) return;
    this.sending.set(true);
    try {
      await this.api.post<Message>('/api/messages', { recipientId: this.otherUserId, content });
      this.content = '';
      await this.loadConversation();
      this.message.set('Mensaje enviado.');
    } catch (error) {
      this.message.set(errorMessage(error));
    } finally {
      this.sending.set(false);
    }
  }
}
